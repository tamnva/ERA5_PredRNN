__author__ = 'yunbo'

import os, sys
import shutil
import argparse
import numpy as np
import math
from core.data_provider import datasets_factory
from core.models.model_factory import Model
from core.utils import preprocess
import core.trainer as trainer
import pywt as pw
import torch.nn as nn
import random

from scipy import ndimage

def center_enhance(img, min_distance = 100, sigma=4, radii=np.arange(0, 20, 2),find_max=True,enhance=True,multiply=2):
    if enhance:
        filter_blurred = ndimage.gaussian_filter(img,1)
        res_img = img + 30*(img - filter_blurred)
    else:
        res_img = ndimage.gaussian_filter(img,3)
    return res_img

def str2bool(v):
    if isinstance(v, bool):
        return v
    if v.lower() in ('yes', 'true', 't', 'y', '1'):
        return True
    elif v.lower() in ('no', 'false', 'f', 'n', '0'):
        return False
    else:
        raise argparse.ArgumentTypeError('Boolean value expected.')

# -----------------------------------------------------------------------------
parser = argparse.ArgumentParser(description='PyTorch video prediction model - PredRNN')

# training/test
parser.add_argument('--is_training', type=int, default=1)
parser.add_argument('--device', type=str, default='cpu:0')

# data
parser.add_argument('--dataset_name', type=str, default='mnist')
parser.add_argument('--train_data_paths', type=str, default='data/moving-mnist-example/moving-mnist-train.npz')
parser.add_argument('--valid_data_paths', type=str, default='data/moving-mnist-example/moving-mnist-valid.npz')
parser.add_argument('--save_dir', type=str, default='checkpoints/mnist_predrnn')
parser.add_argument('--gen_frm_dir', type=str, default='results/mnist_predrnn')
parser.add_argument('--input_length', type=int, default=10)
parser.add_argument('--total_length', type=int, default=20)
parser.add_argument('--img_width', type=int, default=64)
parser.add_argument('--img_height', type=int, default=64)
parser.add_argument('--img_channel', type=int, default=1)
parser.add_argument('--img_layers', type=str, default='1')
parser.add_argument('--concurent_step', type=int, default=1)
parser.add_argument('--use_weight', type=int, default=0)
parser.add_argument('--layer_weight', type=str, default='1,1,1')
parser.add_argument('--skip_time', type=int, default=1)
parser.add_argument('--wavelet', type=str, default='db1')

#center enhancement
parser.add_argument('--center_enhance', type=str2bool, default=False)
parser.add_argument('--layer_need_enhance', type=int, default=0)
parser.add_argument('--find_max', type=str2bool, default=True)
parser.add_argument('--multiply', type=float, default=1.0)

# model
parser.add_argument('--model_name', type=str, default='predrnn')
parser.add_argument('--pretrained_model', type=str, default='')
parser.add_argument('--num_hidden', type=str, default='64,64,64,64')
parser.add_argument('--filter_size', type=int, default=5)
parser.add_argument('--stride', type=int, default=1)
parser.add_argument('--patch_size', type=int, default=4)
parser.add_argument('--patch_size1', type=int, default=4)
parser.add_argument('--layer_norm', type=int, default=1)
parser.add_argument('--decouple_beta', type=float, default=0.1)

# reverse scheduled sampling
parser.add_argument('--reverse_scheduled_sampling', type=int, default=0)
parser.add_argument('--r_sampling_step_1', type=float, default=25000)
parser.add_argument('--r_sampling_step_2', type=int, default=50000)
parser.add_argument('--r_exp_alpha', type=int, default=5000)
# scheduled sampling
parser.add_argument('--scheduled_sampling', type=int, default=1)
parser.add_argument('--sampling_stop_iter', type=int, default=50000)
parser.add_argument('--sampling_start_value', type=float, default=1.0)
parser.add_argument('--sampling_changing_rate', type=float, default=0.00002)

# optimization
parser.add_argument('--lr', type=float, default=0.001)
parser.add_argument('--reverse_input', type=int, default=1)
parser.add_argument('--batch_size', type=int, default=8)
parser.add_argument('--max_iterations', type=int, default=80000)
parser.add_argument('--display_interval', type=int, default=100)
parser.add_argument('--test_interval', type=int, default=5000)
parser.add_argument('--snapshot_interval', type=int, default=5000)
parser.add_argument('--num_save_samples', type=int, default=10)
parser.add_argument('--n_gpu', type=int, default=1)

# visualization of memory decoupling
parser.add_argument('--visual', type=int, default=0)
parser.add_argument('--visual_path', type=str, default='./decoupling_visual')

# action-based predrnn
parser.add_argument('--injection_action', type=str, default='concat')
parser.add_argument('--conv_on_input', type=int, default=0, help='conv on input')
parser.add_argument('--res_on_conv', type=int, default=0, help='res on conv')
parser.add_argument('--num_action_ch', type=int, default=4, help='num action ch')

# new era5 module
parser.add_argument('--is_static', type=int, default=0)
parser.add_argument('--is_scale', type=int, default=0)
parser.add_argument('--out_scale1', type=str, default='')
parser.add_argument('--out_scale2', type=str, default='')
parser.add_argument('--in_scale1', type=str, default='')
parser.add_argument('--in_scale2', type=str, default='')
parser.add_argument('--noise_val', type=float, default=0)
parser.add_argument('--out_channel', type=int, default=5)
parser.add_argument('--stat_layers', type=int, default=8)
parser.add_argument('--stat_layers2', type=int, default=5)
parser.add_argument('--out_weights', type=str, default='')
parser.add_argument('--curr_best_loss', type=float, default=1e5)
parser.add_argument('--isloss', type=int, default=1)
parser.add_argument('--is_logscale', type=int, default=0)
parser.add_argument('--is_WV', type=int, default=0)

args = parser.parse_args()
print(args)

def reserve_schedule_sampling_exp(itr):
    if itr < args.r_sampling_step_1:
        r_eta = 0.5
    elif itr < args.r_sampling_step_2:
        r_eta = 1.0 - 0.5 * math.exp(-float(itr - args.r_sampling_step_1) / args.r_exp_alpha)
    else:
        r_eta = 1.0

    if itr < args.r_sampling_step_1:
        eta = 0.5
    elif itr < args.r_sampling_step_2:
        eta = 0.5 - (0.5 / (args.r_sampling_step_2 - args.r_sampling_step_1)) * (itr - args.r_sampling_step_1)
    else:
        eta = 0.0

    r_random_flip = np.random.random_sample(
        (args.batch_size, args.input_length - 1))
    r_true_token = (r_random_flip < r_eta)

    random_flip = np.random.random_sample(
        (args.batch_size, args.total_length - args.input_length - 1))
    true_token = (random_flip < eta)

    ones = np.ones((args.img_height // args.patch_size,
                    args.img_width // args.patch_size,
                    args.patch_size ** 2 * args.img_channel))
    zeros = np.zeros((args.img_height // args.patch_size,
                      args.img_width // args.patch_size,
                      args.patch_size ** 2 * args.img_channel))

    real_input_flag = []
    for i in range(args.batch_size):
        for j in range(args.total_length - 2):
            if j < args.input_length - 1:
                if r_true_token[i, j]:
                    real_input_flag.append(ones)
                else:
                    real_input_flag.append(zeros)
            else:
                if true_token[i, j - (args.input_length - 1)]:
                    real_input_flag.append(ones)
                else:
                    real_input_flag.append(zeros)
    
    real_input_flag = np.array(real_input_flag)
    real_input_flag = np.reshape(real_input_flag,
                                 (args.batch_size,
                                  args.total_length - 2,
                                  args.img_height // args.patch_size,
                                  args.img_width // args.patch_size,
                                  args.patch_size ** 2 * args.img_channel))
    return real_input_flag


def schedule_sampling(eta, itr):
    zeros = np.zeros((args.batch_size,
                      args.total_length - args.input_length - 1,
                      args.img_height // args.patch_size,
                      args.img_width // args.patch_size,
                      args.patch_size ** 2 * args.img_channel))
    if not args.scheduled_sampling:
        return 0.0, zeros

    if itr < args.sampling_stop_iter:
        eta -= args.sampling_changing_rate
    else:
        eta = 0.0
    random_flip = np.random.random_sample(
        (args.batch_size, args.total_length - args.input_length - 1))
    true_token = (random_flip < eta)
    ones = np.ones((args.img_height // args.patch_size,
                    args.img_width // args.patch_size,
                    args.patch_size ** 2 * args.img_channel))
    zeros = np.zeros((args.img_height // args.patch_size,
                      args.img_width // args.patch_size,
                      args.patch_size ** 2 * args.img_channel))
    real_input_flag = []
    for i in range(args.batch_size):
        for j in range(args.total_length - args.input_length - 1):
            if true_token[i, j]:
                real_input_flag.append(ones)
            else:
                real_input_flag.append(zeros)
    real_input_flag = np.array(real_input_flag)
    real_input_flag = np.reshape(real_input_flag,
                                 (args.batch_size,
                                  args.total_length - args.input_length - 1,
                                  args.img_height // args.patch_size,
                                  args.img_width // args.patch_size,
                                  args.patch_size ** 2 * args.img_channel))
    return eta, real_input_flag


def train_wrapper(model):
    if args.pretrained_model:
        model.load(args.pretrained_model)
    # load data
    train_data_files = args.train_data_paths.split(',')
    if len(train_data_files) <= 3:
        train_input_handle, test_input_handle = datasets_factory.data_provider(
            args.dataset_name, args.train_data_paths, args.valid_data_paths, args.batch_size, args.img_height, 
            args.img_width,
            seq_length=args.total_length, injection_action=args.injection_action, concurent_step=args.concurent_step,
            img_channel = args.img_channel,img_layers = args.img_layers,
            is_training=True,is_WV=args.is_WV)

        eta = args.sampling_start_value

        for itr in range(1, args.max_iterations + 1):
            if train_input_handle.no_batch_left():
                train_input_handle.begin(do_shuffle=True)
            ims = train_input_handle.get_batch()
            ims = ims[:,:,:,:,:args.img_channel]
            #center enhance
            if args.center_enhance:
                enh_ims = ims.copy()
                layer_ims = enh_ims[0,:,:,:,args.layer_need_enhance]
                #unnormalize
                layer_ims = layer_ims *(105000 - 98000) + 98000
                zonal_mean = np.mean(1/(layer_ims[0,:,:]), axis=1) #get lattitude mean of the first time step
                anomaly_zonal = (1/layer_ims) - zonal_mean[None,:,None]
                #re-normalize
                layer_ims = (anomaly_zonal + 3e-7) / 7.7e-7
                enh_ims[0,:,:,:,args.layer_need_enhance] = layer_ims
                ims = enh_ims.copy()
            ims = preprocess.reshape_patch(ims, args.patch_size)
            if args.reverse_scheduled_sampling == 1:
                real_input_flag = reserve_schedule_sampling_exp(itr)
            else:
                eta, real_input_flag = schedule_sampling(eta, itr)

            trainer.train(model, ims, real_input_flag, args, itr)
            if itr % args.snapshot_interval == 0:
                model.save(itr)

            if itr % args.test_interval == 0:
                trainer.test(model, test_input_handle, args, itr)

            train_input_handle.next()
    else: #split trainning files to avoid memory over load
        eta = args.sampling_start_value
        random.shuffle(train_data_files)
        #chunked_train_data_files = [train_data_files[xi:xi+2] for xi in range(0, len(train_data_files), 2)]
        curr_pos = 0
        curr_train_path = train_data_files[curr_pos]
        print(curr_train_path)
        #curr_train_path = ','.join(listi)
        train_input_handle, test_input_handle = datasets_factory.data_provider(
                    args.dataset_name, curr_train_path, 
                    args.valid_data_paths, 
                    args.batch_size, args.img_height, 
                    args.img_width,
                    seq_length=args.total_length, 
                    injection_action=args.injection_action, 
                    concurent_step=args.concurent_step,
                    img_channel = args.img_channel,img_layers = args.img_layers,
                    is_training=True,is_WV=args.is_WV)
        train_input_handle.begin(do_shuffle=True)
        for itr in range(1, args.max_iterations + 1):
            if train_input_handle.no_batch_left():
                if curr_pos < len(train_data_files)-1:
                    curr_pos += 1
                else:
                    curr_pos = 0
                curr_train_path = train_data_files[curr_pos]
                print(curr_train_path)
                #curr_train_path = ','.join(listi)
                train_input_handle, test_input_handle = datasets_factory.data_provider(
                    args.dataset_name, curr_train_path, 
                    args.valid_data_paths, 
                    args.batch_size, args.img_height, 
                    args.img_width,
                    seq_length=args.total_length, 
                    injection_action=args.injection_action, 
                    concurent_step=args.concurent_step,
                    img_channel = args.img_channel,img_layers = args.img_layers,
                    is_training=True,is_WV=args.is_WV)
                train_input_handle.begin(do_shuffle=True)
            
            ims = train_input_handle.get_batch()
            ims = ims[:,:,:,:,:args.img_channel]
            #center enhance
            if args.center_enhance:
                enh_ims = ims.copy()
                layer_ims = enh_ims[0,:,:,:,args.layer_need_enhance]
                #unnormalize
                layer_ims = layer_ims *(105000 - 98000) + 98000
                zonal_mean = np.mean(1/(layer_ims[0,:,:]), axis=1) #get lattitude mean of the first time step
                anomaly_zonal = (1/layer_ims) - zonal_mean[None,:,None]
                #re-normalize
                layer_ims = (anomaly_zonal + 3e-7) / 7.7e-7
                enh_ims[0,:,:,:,args.layer_need_enhance] = layer_ims
                ims = enh_ims.copy()
            ims = preprocess.reshape_patch(ims, args.patch_size)
            if args.reverse_scheduled_sampling == 1:
                real_input_flag = reserve_schedule_sampling_exp(itr)
            else:
                eta, real_input_flag = schedule_sampling(eta, itr)

            trainer.train(model, ims, real_input_flag, args, itr)
            if itr % args.snapshot_interval == 0:
                model.save(itr)

            if itr % args.test_interval == 0:
                trainer.test(model, test_input_handle, args, itr)

            train_input_handle.next()
                

def test_wrapper(model):
    model.load(args.pretrained_model)
    test_input_handle = datasets_factory.data_provider(
        args.dataset_name, args.train_data_paths, args.valid_data_paths, args.batch_size, args.img_height, args.img_width,
        seq_length=args.total_length, injection_action=args.injection_action, concurent_step=args.concurent_step,
        img_channel = args.img_channel,img_layers = args.img_layers,
        is_training=False,is_WV=args.is_WV)
    trainer.test(model, test_input_handle, args, 'test_result')


if os.path.exists(args.save_dir):
    shutil.rmtree(args.save_dir)
os.makedirs(args.save_dir)

if os.path.exists(args.gen_frm_dir):
    shutil.rmtree(args.gen_frm_dir)
os.makedirs(args.gen_frm_dir)

print('Initializing models')

model = Model(args)
#model= nn.DataParallel(model)
#model.to(args.device)

if args.is_training:
    train_wrapper(model)
else:
    test_wrapper(model)
