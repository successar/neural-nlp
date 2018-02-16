from collections import OrderedDict

import keras.backend as K
from keras.layers import Input, Embedding, Lambda
from keras.layers.merge import Dot, Multiply, Add
from keras.models import Model

from keras.optimizers import Adam

from trainer import Trainer
from support import gated_cnn

import numpy as np

def contrastive_loss(y_true, y_pred) :
    return K.mean(K.maximum(0., 1. - y_pred), axis=-1)

class GatedCNNModel(Trainer) :
    def build_model(self, nb_filter=300, filter_lens=range(1,6), reg=0.00001):
        self.aspects = ['bit', 'domain']

        inputs = {}
        inputs['O'] = 'O'
        for aspect in self.aspects :
            for mod in self.modifier :
                inputs[(aspect, mod)] = mod + aspect
                        
        maxlen = self.vec.maxlen
        word_dim, vocab_size = self.vec.word_dim, self.vec.vocab_size

        input = Input(shape=[maxlen], dtype='float32')
        padding = Lambda(lambda s : K.expand_dims(K.clip(s, 0, 1)))(input)

        def mwp(seq) :
            return Multiply()([seq, padding])

        lookup = Embedding(output_dim=word_dim, 
                input_dim=vocab_size, 
                name='embedding',
                weights=[self.vec.embeddings])(input)
        lookup = mwp(lookup)
        
        models = OrderedDict()
        sum_normalize = Lambda(lambda s : K.l2_normalize(K.sum(s, axis=1),axis=-1))

        for aspect in self.aspects:
            network1, gates1 = gated_cnn(lookup, 1, 200, reg)
            network1 = mwp(network1)

            network2, gates2 = gated_cnn(network1, 3, 200, reg)
            network2 = mwp(network2)

            network2 = Add()([network1, network2])
                   
            network3, gates3 = gated_cnn(network2, 5, 200, reg)
            network3 = mwp(network3)

            network3 = Add()([network1, network2, network3])

            gates4 = mwp(gates3)
            
            network3 = Multiply()([network3, gates4])

            network3 = sum_normalize(network3)

            model = Model(input, network3)
            model.name = 'pool_' + aspect
            models[aspect] = model            
                    
        I = OrderedDict()
        for input in inputs :
            I[input] = Input(shape=[maxlen], dtype='float32', name=inputs[input])
                        
        C = OrderedDict()
        for aspect in self.aspects :
            for input in inputs :
                if input in ['O', (aspect, 'S'), (aspect, 'D')] :
                    C[(input, aspect)] = models[aspect](I[input])   

        models_pred = OrderedDict()
        for aspect in self.aspects :
            input_1 = Input(shape=[maxlen], dtype='float32', name='A1')
            input_2 = Input(shape=[maxlen], dtype='float32', name='A2')
            embed_model = models[aspect]
            embed_1 = embed_model(input_1)
            embed_2 = embed_model(input_2)
            output = Dot(axes=1)([embed_1, embed_2])
            model_pred = Model([input_1, input_2], [output])
            model_pred.name = 'pred_'+aspect
            models_pred[aspect] = model_pred

        P = OrderedDict()
        for aspect in self.aspects :
            P[(aspect, 'S')] = models_pred[aspect]([I['O'], I[(aspect, 'S')]])
            P[(aspect, 'D')] = models_pred[aspect]([I['O'], I[(aspect, 'D')]])

                    
        D = OrderedDict()
        self.losses = {}
        
        for aspect in self.aspects :
            name_s = 'O_S'+aspect+'_score'
            D[name_s] = Lambda(lambda s : s[0] - s[1], name=name_s)([P[(aspect, 'S')], P[(aspect, 'D')]])
            self.losses[name_s] = contrastive_loss
                   
        self.model = Model(inputs=I.values(), outputs=D.values())
            
        self.model.compile(optimizer=Adam(lr=0.001), loss=self.losses)
        
    def generate_y_batch(self, nb_sample) :
        y_batch = {}

        ones = []
        zeros = []
        for aspect in self.aspects :
            name_s = 'O_S'+aspect+'_score'
            ones.append(name_s)

        for loss in ones :
            y_batch[loss] = np.ones(nb_sample)
            
        for loss in zeros :
            y_batch[loss] = np.zeros(nb_sample)
            
        return y_batch

    def construct_evaluation_model(self, model, aspect_specific=False) :
        inputs = []
        outputs = []
        for aspect in self.aspects :
            model_aspect = model.get_layer('pred_'+aspect).get_layer('pool_' + aspect)
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
