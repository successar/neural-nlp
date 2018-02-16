from collections import OrderedDict

import keras.backend as K
from keras.layers import Input, Embedding, Dropout, Dense, LSTM, merge, Lambda, Concatenate
from keras.layers import Conv1D, GlobalMaxPooling1D, Flatten, merge
from keras.layers import Activation, Lambda, ActivityRegularization
from keras.layers.merge import Dot, Multiply, Add
from keras.models import Model
from keras.regularizers import l2
from trainer import Trainer

import numpy as np

def contrastive_loss(y_true, y_pred) :
    return K.mean((1 - y_true) * K.maximum(0., y_pred) + (y_true) * K.maximum(0., 1. - y_pred), axis=-1)

class CountModel(Trainer) :
    def build_model(self, nb_filter=100, filter_lens=range(1,6), reg=0.00001):
        self.aspects = ['P', 'I', 'O']

        inputs = {}
        for aspect in self.aspects + ['A'] :
            for mod in self.modifier :
                inputs[(aspect, mod)] = mod + aspect
                        
        vocab_size = self.vec.vocab_size - 2

        input = Input(shape=(vocab_size,), dtype='float32')       
        
        models = OrderedDict()
        gates_models = OrderedDict()

        sum_normalize = Lambda(lambda s : K.l2_normalize(K.sum(s, axis=1),axis=-1))
        normalize = Lambda(lambda s : K.l2_normalize(s, axis=1))

        for aspect in self.aspects + ['E']:
            #gates = Dense(vocab_size, activation='sigmoid', kernel_regularizer=l2(reg))(input)
            #gated_input = Multiply()([input, gates])
            network = Dense(800, activation='relu', kernel_regularizer=l2(reg))(input)
            network = normalize(network)
            model = Model(input, network)
            model.name = 'pool_' + aspect
            models[aspect] = model  

            # gates_network = normalize(gates)
            # gate_model = Model(input, gates_network)
            # gates_models[aspect] = gate_model

        D = OrderedDict()            
        I = OrderedDict()
        for input in inputs :
            I[input] = Input(shape=(vocab_size,), dtype='float32', name=inputs[input])
                        
        C = OrderedDict()
        for aspect in self.aspects + ['E'] :
            for input in inputs :
                C[(input, aspect)] = models[aspect](I[input])     
        
        # G1 = OrderedDict()
        # for aspect in self.aspects + ['E']:
        #     G1[aspect] = gates_models[aspect](I[('A', 'S')])

        # gate_concat = Concatenate()(G1.values())
        # gate_dot = Dot(axes=1)([gate_concat, gate_concat])
        # gate_reg = Lambda(lambda s : 0.1 * K.sum(K.sum(K.square(s - K.eye(4)), axis=-1), 
        #                                     axis=-1, keepdims=True), 
        #                     name='gate_reg')(gate_dot)
                    
        #D['gate_reg'] = gate_reg
        
        self.losses = {}
        #self.losses['gate_reg'] = lambda y_true, y_pred : K.mean(y_pred, axis=-1)
        self.loss_weights = {}

        for aspect in self.aspects :
            embed_1 = C[(('A', 'S'), aspect)]
            for mod in self.modifier :
                embed_2 = C[((aspect, mod), aspect)]
                name = 'SA' + aspect + '_' + mod + aspect + aspect + '_score'
                D[name] = Dot(axes=1, name=name)([embed_1, embed_2])
                self.losses[name] = contrastive_loss
            for aspect_comp in (set(self.aspects) - set([aspect])) :
                embed_2 = C[((aspect_comp, 'S'), aspect)]
                name = 'SA' + aspect + '_S' + aspect_comp + aspect + '_score' 
                D[name] = Dot(axes=1, name=name)([embed_1, embed_2])
                self.losses[name] = contrastive_loss
            
            for mod in ['V', 'C'] :
                embed_2 = C[(('A',mod), aspect)]
                name = 'SA' + aspect + '_' + mod + 'A' + aspect + '_score'
                D[name] = Dot(axes=1, name=name)([embed_1, embed_2])
                self.losses[name] = contrastive_loss
                
            # for mod in ['S', 'V'] :
            #     name = 'SA' + aspect + '_' + mod + aspect + aspect + '_score'
            #     self.loss_weights[name] = 5.0
                
            #self.loss_weights['SA' + aspect + '_' + 'VA' + aspect + '_score'] = 5.0
            
        for aspect in self.aspects :
            embed_1 = C[(('A', 'S'), 'E')]
            embed_2 = C[((aspect, 'S'), 'E')]
            name = 'SAE_S' + aspect + 'E_score'
            D[name] = Dot(axes=1, name=name)([embed_1, embed_2])
            self.losses[name] = contrastive_loss
            
        for mod in ['V', 'C'] :
            embed_1 = C[(('A','S'),'E')]
            embed_2 = C[(('A', mod), 'E')]
            name = 'SAE_' + mod + 'AE_score'
            D[name] = Dot(axes=1, name=name)([embed_1, embed_2])
            self.losses[name] = contrastive_loss
              
        #self.loss_weights['SAE_VAE_score'] = 5.0
                   
        print self.loss_weights
        self.model = Model(inputs=I.values(), outputs=D.values())
            
        self.model.compile(optimizer='adam', loss=self.losses, loss_weights=self.loss_weights)
        
    def generate_y_batch(self, nb_sample) :
        ones = []
        neg_ones = []
        for aspect in self.aspects :
            for mod in ['S', 'V'] :
                name = 'SA' + aspect + '_' + mod + aspect + aspect + '_score'
                ones.append(name)
            mod = 'C'
            name = 'SA' + aspect + '_' + mod + aspect + aspect + '_score'
            neg_ones.append(name)
            for aspect_comp in (set(self.aspects) - set([aspect])) :
                name = 'SA' + aspect + '_S' + aspect_comp + aspect + '_score' 
                neg_ones.append(name)
                
            name = 'SA' + aspect + '_' + 'VA' + aspect + '_score'
            ones.append(name)
            name = 'SA' + aspect + '_' + 'CA' + aspect + '_score'
            neg_ones.append(name)
            
            name = 'SAE_S' + aspect + 'E_score'
            neg_ones.append(name)
            
        ones.append('SAE_VAE_score')
        neg_ones.append('SAE_CAE_score')
        neg_ones.append('gate_reg')
                        
        y_batch = {}
        for loss in ones :
            y_batch[loss] = np.ones(nb_sample)
            
        for loss in neg_ones :
            y_batch[loss] = np.full(shape=nb_sample, fill_value=0)
            
        return y_batch
    
    def construct_evaluation_model(self, model, aspect_specific=False) :
        inputs = []
        outputs = []
        for aspect in self.aspects :
            model_aspect = model.get_layer('pool_' + aspect)
            inputs += model_aspect.inputs
            outputs += model_aspect.outputs
        inputs = inputs[:1]
        inputs += [K.learning_phase()]
        self.aspect_evaluation_models = {}
        for i, aspect in enumerate(self.aspects) :
            self.aspect_evaluation_models[aspect] = K.function(inputs, [outputs[i]])
        output = K.concatenate(outputs, axis=-1)
        self.evaluation_model = K.function(inputs,[output])
        if aspect_specific :
            return self.evaluation_model, self.aspect_evaluation_models
        return self.evaluation_model
