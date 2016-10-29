""" GRU for lemmatization. State-of-the-art lemmatization and
    stemming seems to work through large dictionary lookups and
    hardcoded chopping. Instead we can train a character-level
    NN to map a word to its own lemma.

    There will be a feature per character (padded to some max).
    The POS should also be a feature as it provides info.

"""

from __future__ import absolute_import
from __future__ import print_function

import sys
import cPickle

sys.path.append('../common')
from util import batch_index_generator, split_data

sys.path.append('../models')
import nn_regressor

# to generate a training dataset
import numpy as np
from gensim import models
from nltk import pos_tag, word_tokenize
from nltk.corpus import wordnet
from nltk.stem import WordNetLemmatizer


def treebank_to_simple(penn_tag, default=None):
    morphy_tag = {'NN':wordnet.NOUN,
                  'JJ':wordnet.ADJ,
                  'VB':wordnet.VERB,
                  'RB':wordnet.ADV}
    penn_pre = penn_tag[:2]
    if penn_pre in morphy_tag:
        return morphy_tag[penn_pre]
    return default


def pad_array(array, max_size):
    a = np.zeros(max_size)
    if len(array) > max_size:
        a = array[:max_size]
    else:
        a[:len(array)] = array
    return a


def prepare_sentence(words,
                     pos_dict,
                     vectorizer,
                     lemmatizer,
                     max_words=78,
                     return_output=True):
    X = np.zeros((max_words, 301))
    if return_output:
        y = np.zeros((max_words, 300))

    raw_pos = [p[1]for p in pos_tag(words)]
    pos     = [str(treebank_to_simple(p, default=wordnet.NOUN)) for p in raw_pos]
    if return_output:
        lemmas  = [str(lemmatizer(w, pos=p)) for (w,p) in zip(words, pos)]

    num_words = len(words) if len(words) <= max_words else max_words

    for word_i in range(num_words):
        X[word_i, :300] = vectorizer(words[word_i])
        X[word_i, -1] = pos_dict[raw_pos[word_i]]
        if return_output:
            y[word_i, :] = vectorizer(lemmas[word_i])

    if return_output:
        return X, y
    return X


def gen_dataset(sentences, train_test_split=True, max_words=78):
    ''' Generate a dataset of (input, output) pairs where the
        input is a vector of characters + POS and output is
        a vector of characters for the lemmatized form.

        Args
        ----
        sentences : list of sentences where each sentence is list of tokens
        max_words : maximum number of words allowed in sentence
    '''

    num_sentences = len(sentences)

    # replace me with GloVe when complete
    model = models.Word2Vec.load_word2vec_format(
        '../storage/GoogleNews-vectors-negative300.bin', binary=True)
    with open('../storage/one_hot_list') as f:
        pos_list = cPickle.load(f)
        pos_dict = {}
        for i, pos in enumerate(pos_list):
            pos_dict[pos] = i

    lemmatizer = WordNetLemmatizer().lemmatize
    vectorizer = lambda x: model[x] if x in model else np.zeros(300)
    X = np.zeros((num_sentences, max_words, 301))
    y = np.zeros((num_sentences, max_words, 300))

    param_dict = {}
    param_dict['max_words'] = max_words
    param_dict['pos_dict'] = pos_dict

    for sent_i, words in enumerate(sentences):
        if sent_i % 1000 == 0:
            print("{} sentences parsed. {} remaining.".format(
                sent_i, num_sentences - sent_i - 1))

        X[sent_i, :, :], y[sent_i, :, :] = prepare_sentence(
            words, pos_dict, vectorizer, lemmatizer, max_words=max_words)

    if train_test_split:
        (X_train, X_test), (y_train, y_test) = split_data(
            X, out_data=y, frac=0.80)

        return (X_train, X_test), (y_train, y_test), param_dict
    return (X, y), param_dict


def window_featurizer(X, y, size=[1,1]):
    ''' Given some time series of data, it might be a good idea
        to include some temporal information by adding neighboring
        vectors.

        Args
        ----
        X : 2D numpy
            inputs matrix
        y : 2D numpy
            outputs matrix
        size : list of 2
               first is number prior, second is number after
    '''

    if sum(size) <= 0:
        return X, y

    window_X = np.zeros((X.shape[0] - sum(size), X.shape[1]*(sum(size)+1)))
    window_y = np.zeros((y.shape[0] - sum(size), y.shape[1]))

    for i in range(size[0],X.shape[0]-size[1]-1):
        for j,k in enumerate(range(i-size[0],i+size[1]+1)):
            window_X[i-size[0], j*X.shape[1]:(j+1)*X.shape[1]] = X[k, :]
        window_y[i-size[0], :] = y[i, :]

    return window_X, window_y


def train_lemmatizer(
    obs_set,
    out_set,
    num_hiddens,
    window_size=[0,0],
    batch_size=16,
    param_scale=0.001,
    num_epochs=100,
    step_size=0.001
):
    ''' function to train the NN for mapping vectorized
        characters + POS --> a vectorized lemma

        Args
        ----
        X_train : np array
                  created by gen_dataset
        y_train : np.array
                  created by gen_dataset
        X_test : np.array
                 created by gen_dataset
        y_test : np.array
                 created by gen_dataset
        num_hiddens : integer
                      LSTM hidden nodes
        window_size : integer
                      group nearby vecvtors
        batch_size : integer
                     size of batch in learning
        param_scale : float
                      size of weights if none
        num_epochs : int
                     number of epochs to train
        step_size : float
                    initial step size
    '''

    obs_set = obs_set.reshape(-1, obs_set.shape[-1])
    out_set = out_set.reshape(-1, out_set.shape[-1])

    obs_set, out_set = window_featurizer(obs_set, out_set, size=window_size)

    trained_weights = \
        nn_regressor.train_nn_regressor(obs_set,
                                        out_set,
                                        [1000],
                                        batch_size=batch_size,
                                        param_scale=param_scale,
                                        num_epochs=num_epochs,
                                        step_size=step_size)

    return trained_weights


class NeuralLemmatizer(object):
    ''' Dummy class as a wrapper to easy load the weights and use
        them with one call. Must have a trained nn lemmatizer already.
    '''
    def __init__(self,
                 weights_loc,
                 param_set_loc):
        with open(weights_loc) as fp:
            self.weights = cPickle.load(fp)

        with open(param_set_loc) as fp:
            self.param_set = cPickle.load(fp)
            self.max_words = self.param_set['max_words']
            self.pos_dict = self.param_set['pos_dict']

    def lemmatize(self, sentence):
        X = prepare_sentence(sentence,
                             pos_dict,
                             max_words=78,
                             return_output=True)

        y = lstm.lstm_predict(self.weights, X)
        # convert y back to a bunch of words
        y_words = model.most_similar(positive=y, topn=1)
        return y_words
