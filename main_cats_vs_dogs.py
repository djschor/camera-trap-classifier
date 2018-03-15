""" Train a Model for Cats vs Dogs """
from data_processing.data_inventory import DatasetInventory
#from data_processing.data_reader import DatasetReader
from data_processing.tfr_encoder_decoder import DefaultTFRecordEncoderDecoder
from data_processing.data_reader import DatasetReader
from data_processing.data_writer import DatasetWriter
from data_processing.tfr_splitter import TFRecordSplitter
from pre_processing.image_transformations import (
        preprocess_image,
        preprocess_image_default, resize_jpeg, resize_image)
import tensorflow as tf
import numpy as np
from data_processing.utils  import calc_n_batches_per_epoch, create_default_class_mapper
from config.config import logging
import matplotlib.pyplot as plt

########################
# Parameters
#########################

path_to_images = "D:\\Studium_GD\\Zooniverse\\Data\\cats_vs_dogs\\test"
path_to_images = "D:\\Studium_GD\\Zooniverse\\Data\\transfer_learning_project\\images\\4715\\all"
path_to_tfr_output = "D:\\Studium_GD\\Zooniverse\\Data\\camtrap_trainer\\data\\4715\\"
model_labels = ['primary']
label_mapper = None
n_classes = 2
batch_size = 128
image_save_side_max = 300
image_proc_args = {
    'output_height': 150,
    'output_width': 150,
    'image_means': [0, 0, 0],
    'image_stdevs': [1, 1, 1],
    'is_training': True,
    'resize_side_min': 224,
    'resize_side_max': 500}

# Create Data Inventory
dataset_inventory = DatasetInventory()
dataset_inventory.create_from_class_directories(path_to_images)
dataset_inventory.remove_multi_label_records()


# Create TFRecod Encoder / Decoder
tfr_encoder_decoder = DefaultTFRecordEncoderDecoder()


# Write TFRecord file from Data Inventory
tfr_writer = DatasetWriter(tfr_encoder_decoder.encode_record)
tfr_writer.encode_inventory_to_tfr(
        dataset_inventory,
        path_to_tfr_output + "all.tfrecord",
        image_pre_processing_fun=resize_jpeg,
        image_pre_processing_args={"max_side": image_save_side_max})


# Split TFrecord into Train/Val/Test
tfr_splitter = TFRecordSplitter(
        files_to_split=path_to_tfr_output + "all.tfrecord",
        tfr_encoder=tfr_encoder_decoder.encode_record,
        tfr_decoder=tfr_encoder_decoder.decode_record)

tfr_splitter.split_tfr_file(output_path_main=path_to_tfr_output,
                            output_prefix="split",
                            split_names=['train', 'val', 'test'],
                            split_props=[0.1, 0.05, 0.85],
                            output_labels=model_labels)


# Check numbers
tfr_splitter.log_record_numbers_per_file()
tfr_n_records = tfr_splitter.get_record_numbers_per_file()
tfr_splitter.label_to_numeric_mapper
num_to_label_mapper = {v:k for k, v in tfr_splitter.label_to_numeric_mapper['labels/primary'].items()}


# Create Dataset Reader
data_reader = DatasetReader(tfr_encoder_decoder.decode_record)

# Calculate Dataset Image Means and Stdevs for a dummy batch
batch_data= data_reader.get_iterator(
        tfr_files=[tfr_splitter.get_split_paths()['train']],
        batch_size=1024,
        is_train=False,
        n_repeats=1,
        output_labels=model_labels,
        image_pre_processing_fun=preprocess_image_default,
        image_pre_processing_args=image_proc_args,
        max_multi_label_number=None,
        labels_are_numeric=True)


with tf.Session() as sess:
    data = sess.run(batch_data)


image_means = list(np.mean(data['images'], axis=(0, 1, 2)))
image_stdevs = list(np.std(data['images'], axis=(0, 1, 2)))

image_proc_args['image_means'] = image_means
image_proc_args['image_stdevs'] = image_stdevs


# plot some images and their labels to check
for i in range(0, 30):
    img = data['images'][i,:,:,:]
    lbl = data['labels/primary'][i]
    print("Label: %s" % num_to_label_mapper[int(lbl)])
    plt.imshow(img)
    plt.show()



# Prepare Data Feeders for Training / Validation Data
def input_feeder_train():
    return data_reader.get_iterator(
                tfr_files=[tfr_splitter.get_split_paths()['train']],
                batch_size=batch_size,
                is_train=True,
                n_repeats=None,
                output_labels=model_labels,
                image_pre_processing_fun=preprocess_image_default,
                image_pre_processing_args=image_proc_args,
                max_multi_label_number=None,
                labels_are_numeric=True)


def input_feeder_val():
    return data_reader.get_iterator(
                tfr_files=[tfr_splitter.get_split_paths()['val']],
                batch_size=batch_size,
                is_train=False,
                n_repeats=None,
                output_labels=model_labels,
                image_pre_processing_fun=preprocess_image_default,
                image_pre_processing_args=image_proc_args,
                max_multi_label_number=None,
                labels_are_numeric=True)


n_batches_per_epoch_train = calc_n_batches_per_epoch(tfr_n_records['train'],
                                                     batch_size)

n_batches_per_epoch_val = calc_n_batches_per_epoch(tfr_n_records['val'],
                                                   batch_size)

# Define Model
from tensorflow.python.keras._impl import keras
from tensorflow.python.keras.models import Sequential, Model
from tensorflow.python.keras.layers import Dense, Dropout, Flatten, Input
from tensorflow.python.keras.layers import Conv2D, MaxPooling2D
from tensorflow.python.keras.optimizers import SGD, Adagrad, RMSprop
from tensorflow.python.keras import layers
from tensorflow.python.keras import backend as K
from models.cats_vs_dogs import architecture
import numpy as np
from training.utils import ReduceLearningRateOnPlateau, EarlyStopping



def create_model(input_feeder, n_classes, target_labels):

    target_labels_clean = ['labels/' + x for x in target_labels]

    data = input_feeder()
    model_input = layers.Input(tensor=data['images'])
    model_output = architecture(model_input, n_classes, target_labels_clean)
    model = keras.models.Model(inputs=model_input, outputs=model_output)

    # TODO: build multiple outputs in architecture and map to labels
    target_tensors = {x: tf.cast(data[x], tf.float32) \
                      for x in target_labels_clean}

    opt = SGD(lr=0.01, momentum=0.9, decay=1e-4)
    model.compile(loss='sparse_categorical_crossentropy',
                        optimizer=opt,
                        metrics=['accuracy'],
                        target_tensors=target_tensors)
    return model


reduce_lr_on_plateau = ReduceLearningRateOnPlateau(
        initial_lr = 0.01,
        reduce_after_n_rounds=4,
        stop_after_n_rounds=2,
        reduction_mult=0.1,
        min_lr=1e-4,
        minimize=True
        )

early_stopping = EarlyStopping(stop_after_n_rounds=5)

train_model = create_model(input_feeder_train, n_classes, model_labels)
val_model = create_model(input_feeder_val, n_classes, model_labels)


for i in range(0, 50):
    logging.info("Starting Epoch %s" % (i+1))
    train_model.fit(epochs=i+1,
                    steps_per_epoch=n_batches_per_epoch_train,
                    initial_epoch=i)

    # Copy weights from training model to validation model
    weights = train_model.get_weights()
    val_model.set_weights(weights)

    # Run evaluation model
    results = val_model.evaluate(steps=n_batches_per_epoch_val)

    val_loss = results[val_model.metrics_names=='loss']

    for val, metric in zip(val_model.metrics_names, results):

        logging.info("Eval - %s: %s" % (metric, val))

    # Reduce Learning Rate if necessary
    reduce_lr_on_plateau.addResult(val_loss)
    train_model.optimizer.lr.set_value(reduce_lr_on_plateau.current_lr)

    # Check if training should be stopped
    early_stopping.addResult(val_loss)
    if early_stopping.stop_training:
        logging.info("Early Stopping of Model Training after %s Epochs" %
                     (i+1))
        break



