# -*- coding: utf-8 -*-
"""MyBert_paragraph_TPU.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1mahkJHlx7BMI3uwVTh24PW2o3bO8hzZ9
"""

import datetime
import json
import os
import pprint
import random
import string
import sys
import tensorflow as tf
import pandas as pd
!pip install bert-tensorflow

assert 'COLAB_TPU_ADDR' in os.environ, 'ERROR: Not connected to a TPU runtime; please see the first cell in this notebook for instructions!'
TPU_ADDRESS = 'grpc://' + os.environ['COLAB_TPU_ADDR']
print('TPU address is', TPU_ADDRESS)

from google.colab import auth
auth.authenticate_user()
with tf.Session(TPU_ADDRESS) as session:
  print('TPU devices:')
  pprint.pprint(session.list_devices())

  # Upload credentials to TPU.
  with open('/content/adc.json', 'r') as f:
    auth_info = json.load(f)
  tf.contrib.cloud.configure_gcs(session, credentials=auth_info)
  # Now credentials are set for all future sessions on this TPU.

import sys

!test -d bert_repo || git clone https://github.com/google-research/bert bert_repo
if not 'bert_repo' in sys.path:
  sys.path += ['bert_repo']

# import python modules defined by BERT
from bert import modeling
# import optimization
# import run_classifier
from bert import run_classifier_with_tfhub
# import tokenization

# import tfhub 
import tensorflow_hub as hub

BUCKET = 'bert_example' #@param {type:"string"}
assert BUCKET, 'Must specify an existing GCS bucket name'
OUTPUT_DIR = 'gs://{}/bert-tfhub/models'.format(BUCKET)
tf.gfile.MakeDirs(OUTPUT_DIR)
print('***** Model output directory: {} *****'.format(OUTPUT_DIR))

# Available pretrained model checkpoints:
#   uncased_L-12_H-768_A-12: uncased BERT base model
#   uncased_L-24_H-1024_A-16: uncased BERT large model
#   cased_L-12_H-768_A-12: cased BERT large model
BERT_MODEL = 'uncased_L-12_H-768_A-12' #@param {type:"string"}
BERT_MODEL_HUB = 'https://tfhub.dev/google/bert_' + BERT_MODEL + '/1'

import bert
from bert import run_classifier
from bert import optimization
from bert import tokenization

BERT_MODEL_HUB = "https://tfhub.dev/google/bert_uncased_L-12_H-768_A-12/1" ##Small Bert
# BERT_MODEL_HUB = "https://tfhub.dev/google/bert_uncased_L-24_H-1024_A-16/1" ##Big Bert
def create_tokenizer_from_hub_module():
  """Get the vocab file and casing info from the Hub module."""
  with tf.Graph().as_default():
    bert_module = hub.Module(BERT_MODEL_HUB)
    tokenization_info = bert_module(signature="tokenization_info", as_dict=True)
    with tf.Session() as sess:
      vocab_file, do_lower_case = sess.run([tokenization_info["vocab_file"],
                                            tokenization_info["do_lower_case"]])
      
  return bert.tokenization.FullTokenizer(
      vocab_file=vocab_file, do_lower_case=do_lower_case)

tokenizer = create_tokenizer_from_hub_module()

TRAIN_BATCH_SIZE = 32
EVAL_BATCH_SIZE = 8
PREDICT_BATCH_SIZE = 8
LEARNING_RATE = 2e-5
NUM_TRAIN_EPOCHS = 25.0
MAX_SEQ_LENGTH = 128
# Warmup is a period of time where hte learning rate 
# is small and gradually increases--usually helps training.
WARMUP_PROPORTION = 0.1
# Model configs
SAVE_CHECKPOINTS_STEPS = 200
SAVE_SUMMARY_STEPS = 100

from tensorflow import keras
import os
import re

directory = '/content/alldata_3Dec_7Dec_PS_reindex_train_v3.csv'
data_train = pd.read_csv('/content/alldata_3Dec_7Dec_PS_reindex_train_v3.csv', encoding='latin-1')
data_dev = pd.read_csv('/content/alldata_3Dec_7Dec_PS_reindex_dev_v3.csv', encoding='latin-1')
data_test = pd.read_csv('/content/alldata_3Dec_7Dec_PS_reindex_random_test_v3.csv', encoding='latin-1')
data_test_fixed = pd.read_csv('/content/alldata_3Dec_7Dec_PS_reindex_fixed_test_v3.csv', encoding='latin-1')


def load_paragraphs(df):
    paragraph_labels = []
    paragraph_texts = []
    num_doc = 0
    index = -1
    for doc in df['DOCUMENT']:
      index += 1
      docs = doc.split('\n')
      doc_length = len(docs)

      if pd.isnull(df['Paragraph0'].iloc[index]):
#         Comment the following lines to skip documents with no paragraph labels, I can change it to distant supervision but I don't like :D
#         paragraph_labels.append(df['TRUE_SENTIMENT'].iloc[index])
#         paragraph_texts.append(doc)
        num_doc +=1
        continue
      try:
        if  doc_length != 16 and pd.notnull(df['Paragraph%s'%str(doc_length)].iloc[index]):
          print('error on document %d'% df['DOCUMENT_INDEX'].iloc[index])
          continue
      except:
        print('this document has %d paragraphs %d' %(doc_length,df['DOCUMENT_INDEX'].iloc[index]))


      for i in range(doc_length):
        paragraph_texts.append(docs[i])
        label_i = df['Paragraph%d'%i].iloc[index]
        paragraph_labels.append(label_i)
    print('number of 1 paragraph docs: %d'%num_doc)
    return(paragraph_texts,paragraph_labels)
  

train_par_file = open('/content/alldata_3Dec_7Dec_PS_reindex_train_v3.csv')
train_par_df = pd.read_csv(train_par_file)

dev_par_file = open('/content/alldata_3Dec_7Dec_PS_reindex_dev_v3.csv')
dev_par_df = pd.read_csv(dev_par_file)

test_random_par_file = open('/content/alldata_3Dec_7Dec_PS_reindex_random_test_v3.csv')
test_random_par_df = pd.read_csv(test_random_par_file)

test_fixed_par_file = open('/content/alldata_3Dec_7Dec_PS_reindex_fixed_test_v3.csv')
test_fixed_par_df = pd.read_csv(test_fixed_par_file)


# Load all files from a directory in a DataFrame.
def load_paragraphs_file(df):
  data = {}
  (paragraphs,labels ) = load_paragraphs(df)
  
  data["sentence"] = paragraphs
  data["sentiment"] =labels
  return pd.DataFrame.from_dict(data)

# Merge positive and negative examples, add a polarity column and shuffle.
def load_dataset_par(df,index = None):
  df_new = load_paragraphs_file(df)
  pos_df = df_new[df_new['sentiment'] == 'Positive']
  neg_df = df_new[df_new['sentiment'] == 'Negative']
  neu_df = df_new[df_new['sentiment'] == 'Neutral']
  pos_df["polarity"] = 1
  neg_df["polarity"] = -1
  neu_df["polarity"] = 0
  return pd.concat([pos_df, neg_df,neu_df]).sample(frac=1).reset_index(drop=True)


train_par = load_dataset_par(train_par_df)
dev_par = load_dataset_par(dev_par_df)
test_par = load_dataset_par(test_random_par_df)
test_fixed_par = load_dataset_par(test_fixed_par_df)
print('Number of train paragraphs %d, Number of dev paragraphs %d,  Number of fixed test paragraphs %d,  Number of random test paragraphs %d, '
#       %(len(train_par),len(dev_par),len(test_par),len(test_fixed_par)))

DATA_COLUMN = 'sentence'
LABEL_COLUMN = 'polarity'
label_list = [-1, 0, 1]

train_InputExamples_par = train_par.apply(lambda x: bert.run_classifier.InputExample(guid=None, # Globally unique ID for bookkeeping, unused in this example
                                                                   text_a = x[DATA_COLUMN], 
                                                                   text_b = None, 
                                                                   label = x[LABEL_COLUMN]), axis = 1)

dev_InputExamples_par = dev_par.apply(lambda x: bert.run_classifier.InputExample(guid=None, 
                                                                   text_a = x[DATA_COLUMN], 
                                                                   text_b = None, 
                                                                   label = x[LABEL_COLUMN]), axis = 1)


test_InputExamples_par = test_par.apply(lambda x: bert.run_classifier.InputExample(guid=None, 
                                                                   text_a = x[DATA_COLUMN], 
                                                                   text_b = None, 
                                                                   label = x[LABEL_COLUMN]), axis = 1)

test_InputExamples_fixed_par = test_fixed_par.apply(lambda x: bert.run_classifier.InputExample(guid=None, 
                                                                   text_a = x[DATA_COLUMN], 
                                                                   text_b = None, 
                                                                   label = x[LABEL_COLUMN]), axis = 1)

# train_par_features = bert.run_classifier.convert_examples_to_features(train_InputExamples_par, label_list, MAX_SEQ_LENGTH, tokenizer)
# dev_par_features = bert.run_classifier.convert_examples_to_features(dev_InputExamples_par, label_list, MAX_SEQ_LENGTH, tokenizer)
# test_par_features = bert.run_classifier.convert_examples_to_features(test_InputExamples_par, label_list, MAX_SEQ_LENGTH, tokenizer)
# test_par_features_fixed = bert.run_classifier.convert_examples_to_features(test_InputExamples_fixed_par, label_list, MAX_SEQ_LENGTH, tokenizer)



num_train_steps = int(len(train_InputExamples_par) / TRAIN_BATCH_SIZE * NUM_TRAIN_EPOCHS)
num_warmup_steps = int(num_train_steps * WARMUP_PROPORTION)

# Setup TPU related config
tpu_cluster_resolver = tf.contrib.cluster_resolver.TPUClusterResolver(TPU_ADDRESS)
NUM_TPU_CORES = 8
# ITERATIONS_PER_LOOP = 1000 # I don't know what it is doing just decrease it to smaller value
ITERATIONS_PER_LOOP = int(len(train_InputExamples_par) / TRAIN_BATCH_SIZE) ## set as the number of iterations in each epoch 

def get_run_config(output_dir):
  return tf.contrib.tpu.RunConfig(
    cluster=tpu_cluster_resolver,
    model_dir=output_dir,
    save_checkpoints_steps=SAVE_CHECKPOINTS_STEPS,
    tpu_config=tf.contrib.tpu.TPUConfig(
        iterations_per_loop=ITERATIONS_PER_LOOP,
        num_shards=NUM_TPU_CORES,
        per_host_input_for_training=tf.contrib.tpu.InputPipelineConfig.PER_HOST_V2))

def create_model(is_training, input_ids, input_mask, segment_ids, labels,
                 num_labels, bert_hub_module_handle):
  """Creates a classification model."""
  tags = set()
  if is_training:
    tags.add("train")
  bert_module = hub.Module(bert_hub_module_handle, tags=tags, trainable=True)
  bert_inputs = dict(
      input_ids=input_ids,
      input_mask=input_mask,
      segment_ids=segment_ids)
  bert_outputs = bert_module(
      inputs=bert_inputs,
      signature="tokens",
      as_dict=True)

  # In the demo, we are doing a simple classification task on the entire
  # segment.
  #
  # If you want to use the token-level output, use
  # bert_outputs["sequence_output"] instead.
  output_layer = bert_outputs["pooled_output"]

  hidden_size = output_layer.shape[-1].value

  output_weights = tf.get_variable(
      "output_weights", [num_labels, hidden_size],
      initializer=tf.truncated_normal_initializer(stddev=0.02))

  output_bias = tf.get_variable(
      "output_bias", [num_labels], initializer=tf.zeros_initializer())

  with tf.variable_scope("loss"):
    if is_training:
      # I.e., 0.1 dropout
      output_layer = tf.nn.dropout(output_layer, keep_prob=0.9)

    logits = tf.matmul(output_layer, output_weights, transpose_b=True)
    logits = tf.nn.bias_add(logits, output_bias)
    probabilities = tf.nn.softmax(logits, axis=-1)
    log_probs = tf.nn.log_softmax(logits, axis=-1)

    one_hot_labels = tf.one_hot(labels, depth=num_labels, dtype=tf.float32)

    per_example_loss = -tf.reduce_sum(one_hot_labels * log_probs, axis=-1)
    loss = tf.reduce_mean(per_example_loss)

    return (loss, per_example_loss, logits, probabilities)


def model_fn_builder(num_labels, learning_rate, num_train_steps,
                     num_warmup_steps, use_tpu, bert_hub_module_handle):
  """Returns `model_fn` closure for TPUEstimator."""

  def model_fn(features, labels, mode, params):  # pylint: disable=unused-argument
    """The `model_fn` for TPUEstimator."""

    tf.logging.info("*** Features ***")
    for name in sorted(features.keys()):
      tf.logging.info("  name = %s, shape = %s" % (name, features[name].shape))

    input_ids = features["input_ids"]
    input_mask = features["input_mask"]
    segment_ids = features["segment_ids"]
    label_ids = features["label_ids"]

    is_training = (mode == tf.estimator.ModeKeys.TRAIN)

    (total_loss, per_example_loss, logits, probabilities) = create_model(
        is_training, input_ids, input_mask, segment_ids, label_ids, num_labels,
        bert_hub_module_handle)

    output_spec = None
    if mode == tf.estimator.ModeKeys.TRAIN:
      train_op = optimization.create_optimizer(
          total_loss, learning_rate, num_train_steps, num_warmup_steps, use_tpu)

      output_spec = tf.contrib.tpu.TPUEstimatorSpec(
          mode=mode,
          loss=total_loss,
          train_op=train_op)
    elif mode == tf.estimator.ModeKeys.EVAL:

      def metric_fn(per_example_loss, label_ids, logits):
        predictions = tf.argmax(logits, axis=-1, output_type=tf.int32)
        accuracy = tf.metrics.accuracy(label_ids, predictions)
        loss = tf.metrics.mean(per_example_loss)
        return {
            "eval_accuracy": accuracy,
            "eval_loss": loss,
        }

      eval_metrics = (metric_fn, [per_example_loss, label_ids, logits])
      output_spec = tf.contrib.tpu.TPUEstimatorSpec(
          mode=mode,
          loss=total_loss,
          eval_metrics=eval_metrics)
    elif mode == tf.estimator.ModeKeys.PREDICT:
      output_spec = tf.contrib.tpu.TPUEstimatorSpec(
          mode=mode, predictions={"probabilities": probabilities})
    else:
      raise ValueError(
          "Only TRAIN, EVAL and PREDICT modes are supported: %s" % (mode))

    return output_spec

  return model_fn

# Force TF Hub writes to the GS bucket we provide.
os.environ['TFHUB_CACHE_DIR'] = OUTPUT_DIR

model_fn = model_fn_builder(
  num_labels=len(label_list),
  learning_rate=LEARNING_RATE,
  num_train_steps=num_train_steps,
  num_warmup_steps=num_warmup_steps,
  use_tpu=True,
  bert_hub_module_handle=BERT_MODEL_HUB
)

estimator_from_tfhub = tf.contrib.tpu.TPUEstimator(
  use_tpu=True,
  model_fn=model_fn,
  config=get_run_config(OUTPUT_DIR),
  train_batch_size=TRAIN_BATCH_SIZE,
  eval_batch_size=EVAL_BATCH_SIZE,
  predict_batch_size=PREDICT_BATCH_SIZE,
)

# Train the model
def model_train(estimator):
  # We'll set sequences to be at most 128 tokens long.
  train_features = run_classifier.convert_examples_to_features(
      train_InputExamples_par, label_list, MAX_SEQ_LENGTH, tokenizer)
  print('***** Started training at {} *****'.format(datetime.datetime.now()))
  print('  Num examples = {}'.format(len(train_InputExamples_par)))
  print('  Batch size = {}'.format(TRAIN_BATCH_SIZE))
  tf.logging.info("  Num steps = %d", num_train_steps)
  train_input_fn = run_classifier.input_fn_builder(
      features=train_features,
      seq_length=MAX_SEQ_LENGTH,
      is_training=True,
      drop_remainder=True)
  estimator.train(input_fn=train_input_fn, max_steps=num_train_steps)
  print('***** Finished training at {} *****'.format(datetime.datetime.now()))

# model_train(estimator_from_tfhub)

"""#Evaluation and Prediction"""

def model_eval(estimator):
  # Eval the model.
  eval_examples = dev_InputExamples_par#processor.get_dev_examples(TASK_DATA_DIR)
  eval_features = run_classifier.convert_examples_to_features(
      eval_examples, label_list, MAX_SEQ_LENGTH, tokenizer)
  print('***** Started evaluation at {} *****'.format(datetime.datetime.now()))
  print('  Num examples = {}'.format(len(eval_examples)))
  print('  Batch size = {}'.format(EVAL_BATCH_SIZE))

  # Eval will be slightly WRONG on the TPU because it will truncate
  # the last batch.
  eval_steps = int(len(eval_examples) / EVAL_BATCH_SIZE)
  eval_input_fn = run_classifier.input_fn_builder(
      features=eval_features,
      seq_length=MAX_SEQ_LENGTH,
      is_training=False,
      drop_remainder=True)
  result = estimator.evaluate(input_fn=eval_input_fn, steps=eval_steps)
  print('***** Finished evaluation at {} *****'.format(datetime.datetime.now()))
  output_eval_file = os.path.join(OUTPUT_DIR, "eval_results.txt")
  with tf.gfile.GFile(output_eval_file, "w") as writer:
    print("***** Eval results *****")
    for key in sorted(result.keys()):
      print('  {} = {}'.format(key, str(result[key])))
      writer.write("%s = %s\n" % (key, str(result[key])))

# model_eval(estimator_from_tfhub)

#   eval_accuracy = 0.5473958
#   eval_loss = 1.1722633
#   global_step = 909
#   loss = 1.2637016
  
  
#   ***** Eval results *****
#   eval_accuracy = 0.5375
#   eval_loss = 1.2887536
#   global_step = 1212
#   loss = 1.3013718
def model_predict(estimator,prediction_examples):
  # Make predictions on a subset of eval examples
#   prediction_examples = processor.get_dev_examples(TASK_DATA_DIR)[:PREDICT_BATCH_SIZE]
  input_features = run_classifier.convert_examples_to_features(prediction_examples, label_list, MAX_SEQ_LENGTH, tokenizer)
  predict_input_fn = run_classifier.input_fn_builder(features=input_features, seq_length=MAX_SEQ_LENGTH, is_training=False, drop_remainder=True)
  predictions = estimator.predict(predict_input_fn)
  return [(sentence, prediction['probabilities']) for sentence, prediction in zip(prediction_examples, predictions)]

predictions = model_predict(estimator_from_tfhub,dev_InputExamples_par)

import numpy as np
from sklearn import metrics

labels = ["Negative","Neutral", "Positive"]
labels_val = []
for item in predictions:
  labels_val.append(labels[np.argmax(item[1])])
true_label = list(dev_par['sentiment'])
print(metrics.confusion_matrix(y_pred=labels_val,y_true=true_label))
print(metrics.classification_report(y_pred=labels_val,y_true = true_label))

predictions = model_predict(estimator_from_tfhub,test_InputExamples_fixed_par)
labels_val = []
for item in predictions:
  labels_val.append(labels[np.argmax(item[1])])
true_label = list(test_fixed_par['sentiment'])

print(metrics.confusion_matrix(y_pred=labels_val,y_true=true_label))
print(metrics.classification_report(y_pred=labels_val,y_true = true_label))

predictions = model_predict(estimator_from_tfhub,test_InputExamples_par)
labels_val = []
for item in predictions:
  labels_val.append(labels[np.argmax(item[1])])
true_label = list(test_par['sentiment'])

print(metrics.confusion_matrix(y_pred=labels_val,y_true=true_label))
print(metrics.classification_report(y_pred=labels_val,y_true = true_label))

