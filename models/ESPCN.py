from __future__ import division
import os
import time
import tensorflow as tf
import scipy.misc
import scipy.io
import numpy as np
from glob import glob
from utils import *
from ops import *
from dataloader import *
from subpixel import *

class ESPCN(object):
    def __init__(self, sess, config, dataset_LR, dataset_HR):
        print("Creating ESPCNx%d" %config.scale)
        # copy training parameters
        self.sess = sess
        self.config = config
        self.batch_size = config.batch_size
        self.patch_size = config.patch_size
        self.scale = config.scale
        self.mode = config.mode
        self.channels = config.channels
        self.augmentation = config.augmentation
        
        self.content_layer = config.content_layer
        self.vgg_dir = config.vgg_dir
        
        self.model_name = config.model_name
        self.testset_name = config.testset_name
        self.dataset_name = config.dataset_name
        self.dataset_LR = dataset_LR
        self.dataset_HR = dataset_HR
        
        # loss weights
        self.w_losses = config.w_losses
        
        # patches for training (fixed size)
        self.LR_patch = tf.placeholder(tf.float32, [None, self.patch_size, self.patch_size, self.channels], name='input_LR_patch') 
        self.HR_patch = tf.placeholder(tf.float32, [None, self.patch_size * self.scale, self.patch_size * self.scale, self.channels], name='input_HR_patch') 
          
        # test placeholder for the generator (unknown size)
        #self.LR_test = tf.placeholder(tf.float32, [None, None, None, self.channels], name='input_LR_test_unknown_size')
        self.LR_test = tf.placeholder(tf.float32, [None, None, None, self.channels], name='input_LR_test_unknown_size')
        
        # builc models
        self.build_model()
        
        # build loss function
        self.build_loss()
        tf.global_variables_initializer().run(session=self.sess)
        
        self.saver = tf.train.Saver(tf.trainable_variables())
        self.loss_log = []
        self.PSNR_log = []

    def build_generator(self):
        self.enhanced_patch = self.network(self.LR_patch) 
        self.enhanced_image = self.network(self.LR_test)
        
        variables = tf.trainable_variables()
        self.g_var = [x for x in variables if 'generator' in x.name]
        print("Completed building generator. Number of variables:",len(self.g_var))
        #print(self.g_var)
        
    def generator_network(self, LR):
        with tf.variable_scope('generator', reuse=tf.AUTO_REUSE):
            
            feature_tmp = tf.layers.conv2d(LR, 64, 5, strides = 1, padding = 'SAME', name = 'CONV_1',
                                kernel_initializer = tf.contrib.layers.xavier_initializer(), reuse=tf.AUTO_REUSE)
            feature_tmp = tf.nn.relu(feature_tmp)
            feature_tmp = tf.layers.conv2d(feature_tmp, 32, 3, strides = 1, padding = 'SAME', name = 'CONV_2',
                                kernel_initializer = tf.contrib.layers.xavier_initializer(), reuse=tf.AUTO_REUSE)
            feature_tmp = tf.nn.relu(feature_tmp)
            feature_out = tf.layers.conv2d(feature_tmp, self.channels*self.scale*self.scale, 3, strides = 1, padding = 'SAME', 
                            name = 'CONV_3', kernel_initializer = tf.contrib.layers.xavier_initializer()
            feature_out = PS(feature_out, self.scale, color=False)
            feature_out = tf.layers.conv2d(feature_out, 1, 1, strides = 1, padding = 'SAME', 
                        name = 'CONV_OUT', kernel_initializer = tf.contrib.layers.xavier_initializer(), reuse=tf.AUTO_REUSE)
            return feature_out
            return temp 
    
    def build_loss(self):
        self.loss = tf.reduce_mean(tf.square(self.HR_patch - self.enhanced_patch))

        # calculate generator loss as a weighted sum
        self.G_loss = self.loss
        self.G_optimizer = tf.train.AdamOptimizer(self.config.learning_rate).minimize(self.G_loss, var_list=self.g_var)
    
    def train(self, load = True):
        if load == True:
            self.load()
        else:
            print("Overall training starts from beginning")
        start = time.time()
        start_index = 0
        print("Number of images: %d, batch size: %d, num_repeat: %d --> each epoch consists of %d iterations"
              %(len(self.dataset_HR), self.config.batch_size, self.config.repeat, int(self.config.repeat * len(self.dataset_HR) / self.config.batch_size)))
        for i in range(0, self.config.epochs + 1):
            for batch in range(0, int(self.config.repeat * len(self.dataset_HR) / self.config.batch_size)):
                start_index = (start_index + self.config.batch_size) % len(self.dataset_HR)
                LR_batch, HR_batch = get_batch_Y(self.dataset_LR, self.dataset_HR, self.config.batch_size, self.config, start = start_index)
                _, enhanced_batch, g_loss = self.sess.run([self.G_optimizer, self.enhanced_patch, self.G_loss] , feed_dict={self.LR_patch:LR_batch, self.HR_patch:HR_batch})
            
            if i % self.config.test_every == 0:
                print("------Epoch %d, runtime: %.3f s, generator loss: %.6f" %(1+len(self.PSNR_log), time.time()-start, g_loss))
            
                model_PSNR, bicubic_PSNR = self.test_generator(200, 5, test_discriminator = False)
                self.loss_log.append(g_loss)
                self.PSNR_log.append(model_PSNR)
                save_figure_epoch(len(self.PSNR_log), self.PSNR_log, 'PSNR', self.config.result_dir)
                save_figure_epoch(len(self.loss_log), self.loss_log, 'Loss', self.config.result_dir)
                print("Test PSNR: %.3f (best: %.3f at epoch %d), bicubic: %.3f" %(model_PSNR, max(self.PSNR_log), self.PSNR_log.index(max(self.PSNR_log))+1, bicubic_PSNR))
                self.save("model_latest")
                if model_PSNR >= max(self.PSNR_log):
                    self.save("model_best") 
     
    def test_generator(self, test_num_patch = 200, test_discriminator = False, load = False):
        if load == True:
            self.load()

        # test discriminator for patches
        if test_discriminator == True:
            self.test_discriminator(200, load = False, mode = "enhanced")
        
        # test generator for images
        start = time.time()
        test_list_HR = sorted(glob(self.config.test_path_HR))
        test_list_LR = sorted(glob(self.config.test_path_LR))
        PSNR_HR_enhanced_list = np.zeros([len(test_list_HR)])
        PSNR_HR_bicubic_list = np.zeros([len(test_list_HR)])
        indexes = []
        for i in range(len(test_list_HR)):
            index = i
            indexes.append(index)
            test_image_HR = imageio.imread(test_list_HR[index])#.astype("float64")
            #crop test image
            test_image = test_image_HR[0:int(test_image_HR.shape[0]/self.scale)*self.scale, 0:int(test_image_HR.shape[1]/self.scale)*self.scale, :]
            test_image_LR = imageio.imread(test_list_LR[index])#.astype("float64")
            #test_image_bicubic = imresize(test_image_LR, [test_image.shape[0], test_image.shape[1]], interp = "bicubic")
            start = time.time()
            test_image_bicubic = cv2.resize(test_image_LR, dsize = (0,0), fx = self.scale, fy = self.scale, interpolation = cv2.INTER_CUBIC )
            end = time.time()
            #print("bicubic runtime:", end-start)
            test_image_Y = get_Y(test_image)
            test_image_LR_Y = get_Y(test_image_LR)
            test_image_bicubic_Y = get_Y(test_image_bicubic)
            #print("img shape:", test_image_LR_Y.shape, test_image_Y.shape)
            start = time.time()
            test_image_enhanced = self.sess.run(self.enhanced_image 
                                                , feed_dict={self.LR_test:[preprocess_Y(test_image_LR_Y)],
                                                            self.bicubic_test: [preprocess_Y(test_image_bicubic_Y)]})
            end = time.time()
            #print("image size: ", test_image_Y.shape, ", inference time:", end-start)
            #imageio.imwrite(("./samples/%s/%d_HR.png" %(self.config.testset_name, i)), test_image.astype("uint8"))
            #imageio.imwrite(("./samples/%s/%d_LR.png" %(self.config.testset_name, i)), test_image_LR.astype("uint8"))
            #imageio.imwrite(("./samples/%s/%d_bicubic.png" %(self.config.testset_name, i)), test_image_bicubic.astype("uint8"))
            #imageio.imwrite(("./samples/%s/%d_enhanced.png" %(self.config.testset_name, i)), postprocess(test_image_enhanced[0]))
            #print(postprocess_Y(test_image_enhanced[0]).shape)
            PSNR = calc_PSNR(postprocess_Y(test_image_enhanced[0]), test_image_Y)
            #print("PSNR: %.3f" %PSNR)
            PSNR_HR_enhanced_list[i] = PSNR
            
            test_image_bicubic = imresize(test_image_LR, [test_image.shape[0], test_image.shape[1]], interp = "bicubic")
            test_image_bicubic_Y = get_Y(test_image_bicubic)
            PSNR = calc_PSNR(test_image_bicubic_Y, test_image_Y)
            #print("PSNR: %.3f" %PSNR)
            PSNR_HR_bicubic_list[i] = PSNR
        #if len(test_list_HR) > 0:
        #    print("(runtime: %.3f s) Average test PSNR for %d %s test images: %.3f, bicubic: %.3f" %(time.time()-start, len(test_list_HR), self.config.testset_name, np.mean(PSNR_HR_enhanced_list), np.mean(PSNR_HR_bicubic_list)))
        return np.mean(PSNR_HR_enhanced_list), np.mean(PSNR_HR_bicubic_list)
    
    def save(self, model_name = "model_latest"):
        self.saver.save(self.sess, os.path.join(self.config.checkpoint_dir, model_name), write_meta_graph=False)

    def load(self, model_name = ''):
        self.saver.restore(self.sess, os.path.join(self.config.checkpoint_dir, "model_best")) 
        
        self.loss_log = []
        self.PSNR_log = []
        filename = os.path.join(self.config.result_dir, "PSNR.csv")
        f = open(filename, 'r', encoding='utf-8')
        rdr = csv.reader(f)
        for line in rdr:
            self.PSNR_log.append(float(line[0]))
        f.close() 
        filename = os.path.join(self.config.result_dir, "Loss.csv")
        f = open(filename, 'r', encoding='utf-8')
        rdr = csv.reader(f)
        for line in rdr:
            self.loss_log.append(float(line[0]))
        f.close() 
        print("Continuing from epoch %d" %len(self.PSNR_log))
        
