"""
    @author  jasonYu
    @date    2017/6/3
    @version created
    @email   yuquanjie13@gmail.com
"""
from keras.layers import Convolution2D, MaxPooling2D, BatchNormalization
from keras.layers.convolutional import Conv2DTranspose
from keras.layers.merge import add
from keras.layers.core import Lambda
from keras.callbacks import ModelCheckpoint
from keras import optimizers
from keras.layers import Input
from keras.models import Model, load_model
from keras.preprocessing.image import list_pictures
from tools.get_data import get_zone
from matplotlib import pyplot as plt
import copy
import tools.point_check as point_check
import cv2
import string
import numpy as np
import os
import re
import h5py
import tensorflow as tf
import datetime


def tf_count(t, val):
    """
    https://stackoverflow.com/questions/36530944/how-to-get-the-count-of-an-element-in-a-tensor
    :param t:
    :param val:
    :return:
    """
    elements_equal_to_value = tf.equal(t, val)
    as_ints = tf.cast(elements_equal_to_value, tf.int32)
    count = tf.reduce_sum(as_ints)
    return count


def read_multi_h5file(filelist):
    """
    read multi h5 file
    :param filelist:
    :return: network input X and output Y
    """
    read = h5py.File(filelist[0], 'r')
    x_train = read['X_train'][:]
    y_1_cls = read['Y_train_cls'][:]
    y_2_mer = read['Y_train_merge'][:]
    read.close()

    for idx in range(1, len(filelist)):
        read = h5py.File(filelist[idx], 'r')
        x_ite = read['X_train'][:]
        y_1_cls_ite = read['Y_train_cls'][:]
        y_2_mer_ite = read['Y_train_merge'][:]
        read.close()
        x_train = np.concatenate((x_train, x_ite))
        y_1_cls = np.concatenate((y_1_cls, y_1_cls_ite))
        y_2_mer = np.concatenate((y_2_mer, y_2_mer_ite))

    y_train = [y_1_cls, y_2_mer]
    return x_train, y_train


def l2(y_true, y_pred):
    """
    L2 loss, not divide batch size
    :param y_true: Ground truth for category, negative is 0, positive is 1
                   tensor shape (?, 80, 80, 2)
                   (?, 80, 80, 0): classification label
                   (?, 80, 80, 1): mask label,
                                   0 represent margin between pisitive and negative region, not contribute to loss
                                   1 represent positive and negative region
    :param y_pred:
    :return: A tensor (1, ) total loss of a batch / all contributed pixel
    """
    # extract mask label
    mask_label = tf.expand_dims(y_true[:, :, :, 1], axis=-1)
    # count the number of 1 in mask_label tensor, number of contributed pixels(for each output feature map in batch)
    num_contributed_pixel = tf_count(mask_label, 1)
    # extract classification label
    clas_label = tf.expand_dims(y_true[:, :, :, 0], axis=-1)
    # int32 to flot 32
    num_contributed_pixel = tf.cast(num_contributed_pixel, tf.float32)

    loss = tf.reduce_sum(tf.multiply(mask_label, tf.square(clas_label - y_pred))) / num_contributed_pixel
    # divide batch_size
    # loss = loss / tf.to_float(tf.shape(y_true)[0])
    return loss


def my_hinge(y_true, y_pred):
    """
    Compute hinge loss for classification, return batch loss, not divide batch_size
    :param y_true: Ground truth for category, negative is 0, positive is 1
                   tensor shape (?, 80, 80, 2)
                   (?, 80, 80, 0): classification label
                   (?, 80, 80, 1): mask label,
                                   0 represent margin between pisitive and negative region, not contribute tot loss
                                   1 represent positive and negative region
    :param y_pred:
    :return: tensor shape (1, ), batch total loss / contirbuted pixels
    """
    # extract mask label
    mask_label = tf.expand_dims(y_true[:, :, :, 1], axis=-1)
    # count the number of 1 in mask_label tensor, the number of contributed pixels
    num_contributed_pixel = tf_count(mask_label, 1)
    # extract classification label
    clas_label = tf.expand_dims(y_true[:, :, :, 0], axis=-1)
    # int32 to flot 32
    num_contributed_pixel = tf.cast(num_contributed_pixel, tf.float32)

    exper_1 = tf.sign(0.5 - clas_label)
    exper_2 = y_pred - clas_label
    loss_mask = tf.multiply(mask_label, tf.square(tf.maximum(0.0, exper_1 * exper_2)))

    # sum over all axis, and reduce all dimensions
    loss = tf.reduce_sum(loss_mask) / num_contributed_pixel
    # divide batch_size
    # loss = loss / tf.to_float(tf.shape(y_true)[0])
    return loss


def new_smooth(y_true, y_pred):
    """
    Compute regression loss
    :param y_true: ground truth of regression and classification
                   tensor shape (batch_size, 80, 80, 10)
                   (:, :, :, 0:8) is regression label
                   (:, :, :, 8) is classification label
                   (:, :, :, 9) is mask label
    :param y_pred:
    :return: every pixel loss, average loss of 8 feature map
             tensor shape(batch_size, 80, 80)
    """
    # extract classification label and mask label
    cls_label = tf.expand_dims(y_true[:, :, :, 8], axis=-1)
    mask_label = tf.expand_dims(y_true[:, :, :, 9], axis=-1)
    num_contibuted_pixel = tf.cast(tf_count(mask_label, 1), tf.float32)
    expanded_mask_label = tf.expand_dims(y_true[:, :, :, 9], axis=-1)
    # expand dimension of y_true, from (batch_size, 80, 80, 9) to (batch_size, 80, 80, 16)
    for i in xrange(7):
        y_true = tf.concat([y_true, cls_label], axis=-1)
    # expand dimension of mask label to make it equal to y_pred
    for i in xrange(7):
        expanded_mask_label = tf.concat([expanded_mask_label, mask_label], axis=-1)

    abs_val = tf.abs(y_true[:, :, :, 0:8] - y_pred)
    smooth = tf.where(tf.greater(1.0, abs_val),
                      0.5 * abs_val ** 2,
                      abs_val - 0.5)
    loss = tf.where(tf.greater(y_true[:, :, :, 8:16], 0),
                    smooth,
                    0.0 * smooth)
    loss = tf.multiply(loss, expanded_mask_label)
    # firstly, for a  pixel (x_i, y_i), summing 8 channel's loss, then calculating average loss
    loss = tf.reduce_mean(loss, axis=-1)
    # secondly, sum all dimension loss, then divied number of contributed pixel
    loss = tf.reduce_sum(loss) / num_contibuted_pixel
    # thirdly, divide batch_size
    # loss = loss / tf.to_float(tf.shape(y_true)[0])
    # lambda_loc = 0.01
    lambda_loc = 1
    return lambda_loc * loss


def multi_task_improve(input_tensor):
    im_input = BatchNormalization()(input_tensor)

    # conv_1
    conv1_1 = Convolution2D(32, (5, 5), strides=(1, 1), padding='same',
                            activation='relu', name='conv1_1')(im_input)
    pool1 = MaxPooling2D((2, 2), strides=(2, 2), name='pool1')(conv1_1)

    # conv_2
    conv2_1 = Convolution2D(64, (3, 3), strides=(1, 1), padding='same',
                            activation='relu', name='conv2_1')(pool1)
    conv2_2 = Convolution2D(64, (3, 3), strides=(1, 1), padding='same',
                            activation='relu', name='conv2_2')(conv2_1)
    pool2 = MaxPooling2D((2, 2), strides=(2, 2), name='pool2')(conv2_2)

    # conv_3
    conv3_1 = Convolution2D(128, (3, 3), strides=(1, 1), padding='same',
                            activation='relu', name='conv3_1')(pool2)
    conv3_2 = Convolution2D(128, (3, 3), strides=(1, 1), padding='same',
                            activation='relu', name='conv3_2')(conv3_1)
    pool3 = MaxPooling2D((2, 2), strides=(2, 2), name='pool3')(conv3_2)
    # pool3_for_fuse = Convolution2D(128, (1, 1), strides=(1, 1), padding='same',
    #                               activation='relu', name='pool3_for_fuse')(pool3)

    # conv_4
    conv4_1 = Convolution2D(256, (3, 3), strides=(1, 1), padding='same',
                            activation='relu', name='conv4_1')(pool3)
    conv4_2 = Convolution2D(256, (3, 3), strides=(1, 1), padding='same',
                            activation='relu', name='conv4_2')(conv4_1)
    pool4 = MaxPooling2D((2, 2), strides=(2, 2), name='pool4')(conv4_2)
    # pool4_for_fuse = Convolution2D(128, (1, 1), strides=(1, 1), padding='same',
    #                                activation='relu', name='pool4_for_fuse')(pool4)
    pool4_for_fuse = Convolution2D(128, (3, 3), strides=(1, 1), padding='same',
                                   activation='relu', name='pool4_for_fuse')(pool4)

    # conv_5
    conv5_1 = Convolution2D(512, (3, 3), strides=(1, 1), padding='same',
                            activation='relu', name='conv5_1')(pool4)
    conv5_2 = Convolution2D(512, (3, 3), strides=(1, 1), padding='same',
                            activation='relu', name='conv5_2')(conv5_1)
    pool5 = MaxPooling2D((2, 2), strides=(2, 2), name='pool5')(conv5_2)
    # pool5_for_fuse = Convolution2D(128, (1, 1), strides=(1, 1), padding='same',
    #                                activation='relu', name='pool5_for_fuse')(pool5)
    pool5_for_fuse = Convolution2D(128, (3, 3), strides=(1, 1), padding='same',
                                   activation='relu', name='pool5_for_fuse')(pool5)

    # conv_6
    conv6_1 = Convolution2D(512, (3, 3), strides=(1, 1), padding='same',
                            activation='relu', name='conv6_1')(pool5)
    conv6_2 = Convolution2D(512, (3, 3), strides=(1, 1), padding='same',
                            activation='relu', name='conv6_2')(conv6_1)
    pool6 = MaxPooling2D((2, 2), strides=(2, 2), name='pool6')(conv6_2)

    #
    conv7_1 = Convolution2D(128, (1, 1), strides=(1, 1), padding='same',
                            activation='relu', name='conv7_1')(pool6)

    upscore2 = Conv2DTranspose(filters=128, kernel_size=(2, 2),
                               strides=(2, 2), padding='valid', use_bias=False,
                               name='upscore2')(conv7_1)

    fuse_pool5 = add([upscore2, pool5_for_fuse])
    upscore4 = Conv2DTranspose(filters=128, kernel_size=(2, 2),
                               strides=(2, 2), padding='valid', use_bias=False,
                               name='upscore4')(fuse_pool5)
    fuse_pool4 = add([upscore4, pool4_for_fuse])

    upscore8 = Conv2DTranspose(filters=128, kernel_size=(2, 2),
                               strides=(2, 2), padding='valid', use_bias=False,
                               name='upscore8')(fuse_pool4)
    # fuse_pool3 = add([upscore8, pool3_for_fuse])
    fuse_pool3 = add([upscore8, pool3])

    upscore16 = Conv2DTranspose(filters=128, kernel_size=(2, 2),
                                strides=(2, 2), padding='valid', use_bias=False,
                                name='upscore16')(fuse_pool3)
    ##########################################################################
    # shared layer
    ##########################################################################
    x_clas = Convolution2D(1, (1, 1), strides=(1, 1), padding='same', name='cls')(upscore16)
    # x_clas = Convolution2D(1, (1, 1), strides=(1, 1), padding='same', name='cls', activation='sigmoid')(upscore16)
    x = Convolution2D(128, (1, 1), strides=(1, 1), padding='same', activation='relu')(upscore16)
    x = Convolution2D(8, (1, 1), strides=(1, 1), padding='same', activation='sigmoid')(x)
    x_regr = Lambda(lambda t: 800 * t - 400)(x)
    return [x_clas, x_regr, x]


def multi_task(input_tensor):
    im_input = BatchNormalization()(input_tensor)

    # conv_1
    conv1_1 = Convolution2D(32, (5, 5), strides=(1, 1), padding='same',
                            activation='relu', name='conv1_1')(im_input)
    pool1 = MaxPooling2D((2, 2), strides=(2, 2), name='pool1')(conv1_1)

    # conv_2
    conv2_1 = Convolution2D(64, (3, 3), strides=(1, 1), padding='same',
                            activation='relu', name='conv2_1')(pool1)
    conv2_2 = Convolution2D(64, (3, 3), strides=(1, 1), padding='same',
                            activation='relu', name='conv2_2')(conv2_1)
    pool2 = MaxPooling2D((2, 2), strides=(2, 2), name='pool2')(conv2_2)

    # conv_3
    conv3_1 = Convolution2D(128, (3, 3), strides=(1, 1), padding='same',
                            activation='relu', name='conv3_1')(pool2)
    conv3_2 = Convolution2D(128, (3, 3), strides=(1, 1), padding='same',
                            activation='relu', name='conv3_2')(conv3_1)
    pool3 = MaxPooling2D((2, 2), strides=(2, 2), name='pool3')(conv3_2)
    pool3_for_fuse = Convolution2D(128, (1, 1), strides=(1, 1), padding='same',
                                   activation='relu', name='pool3_for_fuse')(pool3)

    # conv_4
    conv4_1 = Convolution2D(256, (3, 3), strides=(1, 1), padding='same',
                            activation='relu', name='conv4_1')(pool3)
    conv4_2 = Convolution2D(256, (3, 3), strides=(1, 1), padding='same',
                            activation='relu', name='conv4_2')(conv4_1)
    pool4 = MaxPooling2D((2, 2), strides=(2, 2), name='pool4')(conv4_2)
    pool4_for_fuse = Convolution2D(128, (1, 1), strides=(1, 1), padding='same',
                                   activation='relu', name='pool4_for_fuse')(pool4)

    # conv_5
    conv5_1 = Convolution2D(512, (3, 3), strides=(1, 1), padding='same',
                            activation='relu', name='conv5_1')(pool4)
    conv5_2 = Convolution2D(512, (3, 3), strides=(1, 1), padding='same',
                            activation='relu', name='conv5_2')(conv5_1)
    pool5 = MaxPooling2D((2, 2), strides=(2, 2), name='pool5')(conv5_2)
    pool5_for_fuse = Convolution2D(128, (1, 1), strides=(1, 1), padding='same',
                                   activation='relu', name='pool5_for_fuse')(pool5)

    # conv_6
    conv6_1 = Convolution2D(512, (3, 3), strides=(1, 1), padding='same',
                            activation='relu', name='conv6_1')(pool5)
    conv6_2 = Convolution2D(512, (3, 3), strides=(1, 1), padding='same',
                            activation='relu', name='conv6_2')(conv6_1)
    pool6 = MaxPooling2D((2, 2), strides=(2, 2), name='pool6')(conv6_2)

    #
    conv7_1 = Convolution2D(128, (1, 1), strides=(1, 1), padding='same',
                            activation='relu', name='conv7_1')(pool6)

    upscore2 = Conv2DTranspose(filters=128, kernel_size=(2, 2),
                               strides=(2, 2), padding='valid', use_bias=False,
                               name='upscore2')(conv7_1)

    fuse_pool5 = add([upscore2, pool5_for_fuse])
    upscore4 = Conv2DTranspose(filters=128, kernel_size=(2, 2),
                               strides=(2, 2), padding='valid', use_bias=False,
                               name='upscore4')(fuse_pool5)
    fuse_pool4 = add([upscore4, pool4_for_fuse])

    upscore8 = Conv2DTranspose(filters=128, kernel_size=(2, 2),
                               strides=(2, 2), padding='valid', use_bias=False,
                               name='upscore8')(fuse_pool4)
    fuse_pool3 = add([upscore8, pool3_for_fuse])

    upscore16 = Conv2DTranspose(filters=128, kernel_size=(2, 2),
                                strides=(2, 2), padding='valid', use_bias=False,
                                name='upscore16')(fuse_pool3)
    ##########################################################################
    # shared layer
    ##########################################################################
    x_clas = Convolution2D(1, (1, 1), strides=(1, 1), padding='same', name='cls')(upscore16)
    # x_clas = Convolution2D(1, (1, 1), strides=(1, 1), padding='same', name='cls', activation='sigmoid')(upscore16)
    x = Convolution2D(128, (1, 1), strides=(1, 1), padding='same', activation='relu')(upscore16)
    x = Convolution2D(8, (1, 1), strides=(1, 1), padding='same', activation='sigmoid')(x)
    x_regr = Lambda(lambda t: 800 * t - 400)(x)
    return [x_clas, x_regr, x]


def img_txtreg_generator(jpgs_list, crop_size=320, scale=1):
    """
    a python generator, read image's text region from txt file
    :param jpgs_list: list, storing all jpgs's path
    :param crop_size: cropped image size
    :param scale: normalization parameter
    :return: A list [numpy array of image(normalized), text region list]
    """
    vis = False
    while True:
        # a list stores image's text region
        text_reg_list = []
        # choose a image randomly from all images
        jpg_path = np.random.choice(jpgs_list)
        img_nparr = cv2.imread(jpg_path)
        # get image's txt file path
        pattern = re.compile('jpg')
        txt_path = pattern.sub('txt', jpg_path)
        # ensure jpg file has a correspongding txt file
        if not os.path.isfile(txt_path):
            continue
        with open(txt_path, 'r') as f:
            for line in f:
                line_split = line.strip().split(',')
                # clockwise
                (x1, y1, x2, y2) = line_split[0:4]
                (x3, y3, x4, y4) = line_split[4:8]
                text_reg_list.append([string.atof(x1), string.atof(y1), string.atof(x2), string.atof(y2),
                                      string.atof(x3), string.atof(y3), string.atof(x4), string.atof(y4)])
        # ensure jpg and txt file is not empty
        if img_nparr is None or text_reg_list is None:
            continue
        # ensure jpg file's shape is 320 * 320
        if img_nparr.shape[0] != crop_size or img_nparr.shape[1] != crop_size:
            continue

        #       ------------------------------ visualise ------------------------------
        if vis:
            print 'txt_path is {0}'.format(txt_path)
            for bbox in text_reg_list:
                print 'bbox is {0}'.format(bbox)
                # coordinates must be int type
                poly = np.array([[[bbox[0], bbox[1]], [bbox[2], bbox[3]], [bbox[4], bbox[5]], [bbox[6], bbox[7]]]],
                                dtype=np.int32)
                cv2.fillPoly(img_nparr, poly, 255)
            plt.subplot(221)
            b, g, r = cv2.split(img_nparr)
            img_nparr = cv2.merge([r, g, b])
            plt.imshow(img_nparr)
            plt.show()
        #       ------------------------------ visualise ------------------------------
        # normalize image data from [0, 255] to [0, 1]
        scaled_img = scale * img_nparr
        yield [scaled_img, text_reg_list]


def image_ylabel_generator(images):
    """

    :param images:
    :return:
    """
    vis = False
    for img, txtreg in images:
        # 1) generate imput data, input data is (320, 320, 3)

        # 2) generate clsssification data
        # split text region into gray_zone_list and posi_zone_list
        # gray_zone_list is a list, each element represent a gray zone
        gray_zone_list, posi_zone_list = get_zone(txtreg)
        # x-axis and y-axis reduced scale
        reduced_x, reduced_y = float(img.shape[1]) / 80.0, float(img.shape[0]) / 80.0
        mask_label = np.ones((80, 80))
        y_class_label = np.zeros((80, 80))  # negative lable is 0
        for ix in xrange(y_class_label.shape[0]):
            for jy in xrange(y_class_label.shape[1]):
                for posi in posi_zone_list:
                    x1, x2 = posi[0] / reduced_x, posi[2] / reduced_x
                    x3, x4 = posi[4] / reduced_x, posi[6] / reduced_x
                    y1, y2 = posi[1] / reduced_y, posi[3] / reduced_y
                    y3, y4 = posi[5] / reduced_y, posi[7] / reduced_y
                    posi_poly = [(x1, y1), (x2, y2), (x3, y3), (x4, y4)]
                    if point_check.point_in_polygon(ix, jy, posi_poly):
                        y_class_label[ix][jy] = 1
                for gray in gray_zone_list:
                    x1, x2 = gray[0] / reduced_x, gray[2] / reduced_x
                    x3, x4 = gray[4] / reduced_x, gray[6] / reduced_x
                    y1, y2 = gray[1] / reduced_y, gray[3] / reduced_y
                    y3, y4 = gray[5] / reduced_y, gray[7] / reduced_y
                    gray_poly = [(x1, y1), (x2, y2), (x3, y3), (x4, y4)]
                    if point_check.point_in_polygon(ix, jy, gray_poly):
                        mask_label[ix][jy] = 0
        #       ------------------------------ visualise ------------------------------
        if vis:
            # raw image
            # has normalized to [0 -1], should use anti-normalize ?
            # b, g, r = cv2.split(img * 255.0)
            b, g, r = cv2.split(img )
            img = cv2.merge([r, g, b])
            plt.subplot(221)
            plt.imshow(img)

            # positive region
            plt_img = copy.deepcopy(img)
            for ix in xrange(y_class_label.shape[0]):
                for jy in xrange(y_class_label.shape[0]):
                    if y_class_label[ix][jy] == 1:
                        cv2.circle(plt_img, (int(ix) * 4, int(jy) * 4), radius=1, color=(0, 255, 0))
            plt.subplot(222)
            plt.imshow(plt_img)

            # gray region
            mask_img = copy.deepcopy(img)
            for ix in xrange(mask_label.shape[0]):
                for jy in xrange(mask_label.shape[0]):
                    if mask_label[ix][jy] == 0:
                        cv2.circle(mask_img, (int(ix) * 4, int(jy) * 4), 1, color=(255, 0, 0))
            plt.subplot(224)
            plt.imshow(mask_img)

            plt.show()
        #       ------------------------------ visualise ------------------------------
        # calculate ones's locations before expand the dimension of y_class_label
        one_locs = np.where(y_class_label > 0)
        # deep copy for visualize
        copy_class = copy.deepcopy(y_class_label)
        copy_mask = copy.deepcopy(mask_label)
        # print 'y_cls_lable {0}'.format(y_class_label)
        y_class_label = np.expand_dims(y_class_label, axis=-1)
        # print 'y_cls_lable {0}'.format(y_class_label)
        mask_label = np.expand_dims(mask_label, axis=-1)
        #       ------------------------------ visualise ------------------------------
        if vis:
            plt.subplot(221)
            plt.imshow(img)

            plt.subplot(222)
            x, y = np.meshgrid(np.arange(0, 80), np.arange(0, 80))
            copy_class = np.rot90(copy_class, 1).tolist()
            plt.pcolormesh(x, y, copy_class)
            plt.colorbar()  # need a colorbar to show the intensity scale

            plt.subplot(224)
            x, y = np.meshgrid(np.arange(0, 80), np.arange(0, 80))
            copy_mask = np.rot90(copy_mask, 1).tolist()
            plt.pcolormesh(x, y, copy_mask)
            plt.colorbar()  # need a colorbar to show the intensity scale

            plt.show()
        #       ------------------------------ visualise ------------------------------

        # 3) generate regression data
        y_regr_lable = np.zeros((80, 80, 8))
        # visit all text pixel
        for idx in xrange(len(one_locs[0])):
            # judge text pixel belong to which box
            for polygon in txtreg:
                x1, x2 = polygon[0] / reduced_x, polygon[2] / reduced_x
                x3, x4 = polygon[4] / reduced_x, polygon[6] / reduced_x
                y1, y2 = polygon[1] / reduced_y, polygon[3] / reduced_y
                y3, y4 = polygon[5] / reduced_y, polygon[7] / reduced_y
                # 80 * 80 image's quardrangle
                quard = [(x1, y1), (x2, y2), (x3, y3), (x4, y4)]
                ix = one_locs[0][idx]
                jy = one_locs[1][idx]
                # (ix, jy) pixel belong to quardragle quard
                if point_check.point_in_polygon(ix, jy, quard):
                    top_left_x, top_left_y = quard[0][0], quard[0][1]
                    top_righ_x, top_righ_y = quard[1][0], quard[1][1]
                    dow_righ_x, dow_righ_y = quard[2][0], quard[2][1]
                    dow_left_x, dow_left_y = quard[3][0], quard[3][1]

                    y_regr_lable[ix][jy][0] = top_left_x * 4 - ix * 4
                    y_regr_lable[ix][jy][1] = top_left_y * 4 - jy * 4
                    y_regr_lable[ix][jy][2] = top_righ_x * 4 - ix * 4
                    y_regr_lable[ix][jy][3] = top_righ_y * 4 - jy * 4
                    y_regr_lable[ix][jy][4] = dow_righ_x * 4 - ix * 4
                    y_regr_lable[ix][jy][5] = dow_righ_y * 4 - jy * 4
                    y_regr_lable[ix][jy][6] = dow_left_x * 4 - ix * 4
                    y_regr_lable[ix][jy][7] = dow_left_y * 4 - jy * 4
        y_regr_cls_mask_label = np.concatenate((y_regr_lable, y_class_label, mask_label), axis=-1)
        y_cls_mask_label = np.concatenate((y_class_label, mask_label), axis=-1)
        yield (img, y_cls_mask_label, y_regr_cls_mask_label)


def group_by_batch(dataset, batch_size):
    """

    :param dataset:
    :param batch_size:
    :return:
    """
    while True:
        img, y_cls_mask_label, y_regr_cls_mask_label = zip(*[dataset.next() for i in xrange(batch_size)])
        batch = (np.stack(img), [np.stack(y_cls_mask_label), np.stack(y_regr_cls_mask_label)])
        yield batch


def load_dataset(directory, crop_size=320, batch_size=32):
    """
    load data from directory
    :param directory: jpg files directory
    :param crop_size: cropped image size
    :param batch_size: batch size
    :return: python generator object, a batch training data, img, y_cls_mask_lable, y_regr_cls_mask_label
    """
    jpg_list = list_pictures(directory, 'jpg')
    generator = img_txtreg_generator(jpg_list, crop_size, scale=1/255.0)
    generator = image_ylabel_generator(generator)
    generator = group_by_batch(generator, batch_size)
    return generator


if __name__ == '__main__':
    gpu_id = '1'
    os.environ['CUDA_VISIBLE_DEVICES'] = str(gpu_id)

    model_name = 'multi_task'
    batch_size = 64
    batch_momentum = 0.9
    epoches = 300
    lr = 4e-4
    resume_training = False
    target_size = (320, 320)
    dataset = 'ICDAR'
    if dataset == 'ICDAR':
        train_file_path = os.path.expanduser('/home/yuquanjie/Documents/Dataset/icdar/icdar/train.txt')
        val_file_path = os.path.expanduser('/home/yuquanjie/Documents/Dataset/icdar/icdar/val.txt')
        data_dir = os.path.expanduser('/home/yuquanjie/Documents/Dataset/icdar/icdar/data')
        label_dir = os.path.expanduser('/home/yuquanjie/Documents/Dataset/icdar/icdar/data')
        data_suffix = '.jpg'
        label_suffix = '.png'

    if dataset == 'SHUMEI':
        print '2'





    # define input
    img_input = Input((320, 320, 3))
    # define network
    # multi = multi_task_improve(img_input)
    multi = multi_task(img_input)
    multitask_model = Model(img_input, multi[0:2])
    # define optimizer
    sgd = optimizers.SGD(lr=0.01, decay=4e-4, momentum=0.9)
    # compile model
    multitask_model.compile(loss=[my_hinge, new_smooth], optimizer=sgd)
    # resume training, use loading weights(not work, still unknowned reason), not loading model structure
    multitask_model = load_model('model/2017-07-19-18-46-epoch-110-loss-4.09-saved-all-model.hdf5',
                                 custom_objects={'my_hinge': my_hinge, 'new_smooth': new_smooth})

    use_generator = True
    if use_generator:
        shumei = False
        if shumei:
            # shumei data
            train_set = load_dataset('/home/yuquanjie/Documents/shumei_crop_center', 320, 64)
            val_set = load_dataset('/home/yuquanjie/Documents/shumei_crop_center', 320, 64)
        else:
            # icdar data
            train_set = load_dataset('/home/yuquanjie/Documents/Dataset/icdar/crop_center_rotated', 320, 64)
            val_set = load_dataset('/home/yuquanjie/Documents/Dataset/icdar/crop_center_rotated_test', 320, 64)

        date_time = datetime.datetime.now().strftime('%Y-%m-%d-%H-%M')
        filepath = "model/" + date_time + "-epoch-{epoch:02d}-loss-{loss:.2f}-saved-all-model.hdf5"
        checkpoint = ModelCheckpoint(filepath, monitor='loss', verbose=1, save_best_only=True,
                                     save_weights_only=False, mode='min')
        callbacks_list = [checkpoint]
        multitask_model.fit_generator(train_set, steps_per_epoch=100, epochs=10000, callbacks=callbacks_list,
                                      validation_data=val_set, validation_steps=1508 // 64, initial_epoch=114)
    else:
        print 'reading data from h5 file .....'
        filenamelist = ['dataset/train_1', 'dataset/train_2', 'dataset/train_3']
        X, Y = read_multi_h5file(filenamelist)
        print 'traning data, input shape is {0}, output classifiction shape is {1}, regression shape is {2}'. \
            format(X.shape, Y[0].shape, Y[1].shape)
        # get date and time
        date_time = datetime.datetime.now().strftime('%Y-%m-%d-%H-%M')
        filepath = "model/" + date_time + "-loss-decrease-{epoch:02d}-{loss:.2f}-saved-weights.hdf5"
        checkpoint = ModelCheckpoint(filepath, monitor='loss', verbose=1, save_weights_only=True, mode='min')
        callbacks_list = [checkpoint]
        multitask_model.fit(X, Y, batch_size=64, epochs=10000, shuffle=True, callbacks=callbacks_list,
                            verbose=1, validation_split=0.1)
