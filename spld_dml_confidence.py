# -*- coding: utf-8 -*-

from __future__ import print_function
from __future__ import division

__docformat__ = 'restructedtext en'

import pdb

import six.moves.cPickle as cPickle
import gzip
import os
import sys
import timeit
import time

from math import ceil

import numpy
numpy.random.seed(5)

from tqdm import tqdm

import matplotlib.pyplot as pyplot

import torch
import torch.nn as nn
from torch.autograd import Variable
import torch.nn.functional as F
from torch.utils.data import DataLoader
from torch import optim

import torchvision
from torchvision.datasets import MNIST, CIFAR10
from torchvision import transforms
import torch.backends.cudnn as cudnn

import visdom

from utils.train_settings import parse_settings
from utils.cluster_dataset import group_data, compute_clusters, get_cluster
from datasets.load_dataset import load_dataset

from models.lenet import LeNet, FashionLeNet, LeNetCifar10
from models.preact_resnet import PreActResNet18
from models.resnet import ResNetCifar10
from models.googlenet import GoogLeNet
from models.wide_resnet import Wide_ResNet
from models.wide_resnet_confidence import Wide_ResNet_Conf

from utils.sampler import SubsetSequentialSampler
from utils.min_max_sort import min_max_sort

import matplotlib.pyplot as plt

from utils.average_meter import AverageMeter
from visualizer.visualize import VisdomLinePlotter

# used for logging to TensorBoard
from tensorboard_logger import configure, log_value

from magnet_loss.magnet_tools import *

from utils.sampler import SubsetSequentialSamplerSPLDML

import pdb
import random
#viz = visdom.Visdom()

args = parse_settings()

args.cuda = not args.no_cuda and torch.cuda.is_available()

torch.manual_seed(args.seed)
if args.cuda:
	torch.cuda.manual_seed(args.seed)

class StableBCELoss(nn.modules.Module):
       def __init__(self):
             super(StableBCELoss, self).__init__()
       def forward(self, input, target):
             neg_abs = - input.abs()
             loss = input.clamp(min=0) - input * target + (1 + neg_abs.exp()).log()
             return loss

def save_checkpoint(state, is_best, filename='checkpoint.pth.tar'):
    """Saves checkpoint to disk"""
    directory = "runs/%s/"%(args.name)
    if not os.path.exists(directory):
        os.makedirs(directory)
    filename = directory + filename
    torch.save(state, filename)
    if is_best:
        shutil.copyfile(filename, 'runs/%s/'%(args.name) + 'model_best.pth.tar')

def encode_onehot(labels, n_classes):
	'''
		One hot encode the labels, which is used for calculating the
		loss per sample
	'''
	onehot = torch.FloatTensor(labels.size()[0], n_classes)
	labels = labels.data

	if labels.is_cuda:
		onehot = onehot.cuda()

	onehot.zero_()
	onehot.scatter_(1, labels.view(-1, 1), 1)

	return onehot

def extract_features(model, n_train, trainloader):
	start_index = 0
	#train_features = ()
	train_features_seq = ()
	for batch_idx, (img, target) in tqdm(enumerate(trainloader)):
		#print(img)
		#xit()
		end_index = min([start_index + args.batch_size, n_train])
		#print("End index: {}".format(end_index))
		batch_index = range(start_index, end_index)
		#print("Batch index: {}".format(batch_index))
		start_index = end_index
		#print("Start index: {}".format(start_index))
		img = Variable(img).cuda()
		_, train_features = model(img)
		train_features = train_features.data
		#print(train_features.cpu().numpy())
		#print(type(train_features.cpu().numpy()))
		train_features_seq = train_features_seq + (train_features.cpu().numpy(), )

	#print(" ")
	#print("End index: {}".format(end_index))
	#print("Batch index: {}".format(batch_index))
	#print("Start index: {}".format(start_index))

	# Generate labels, cluster centers, nn_center
	#train_features_seq = numpy.vstack(train_features_seq)

	return numpy.vstack(train_features_seq)

def adjust_learning_rate(optimizer, epoch):
    """Sets the learning rate to the initial LR divided by 5 at 60th, 120th and 160th epochs"""
    lr = args.lr * ((0.2 ** int(epoch >= 60)) * (0.2 ** int(epoch >= 120))* (0.2 ** int(epoch >= 160)))
    # log to TensorBoard
    if args.tensorboard:
        log_value('learning_rate', lr, epoch)
    for param_group in optimizer.param_groups:
        param_group['lr'] = lr

# def adjust_learning_rate(optimizer, epoch, lr):
#     """Sets the learning rate to the initial LR divided by 5 after 60, 120 and 160 epochs"""
#     # lr = args.lr * ((0.5 ** int(epoch > 60)) * (0.5 ** int(epoch > 120))* (0.5 ** int(epoch > 160)))
#     lr = lr * (0.92 ** int(epoch % 3 == 0))
#     print(lr)
#     # log to TensorBoard
#     if args.tensorboard:
#         log_value('learning_rate', lr, epoch)
#     for param_group in optimizer.param_groups:
#         param_group['lr'] = lr

def accuracy(output, target, topk=(1,)):
    """Computes the precision@k for the specified values of k"""
    maxk = max(topk)
    batch_size = target.size(0)

    _, pred = output.topk(maxk, 1, True, True)
    pred = pred.t()
    correct = pred.eq(target.view(1, -1).expand_as(pred))

    res = []
    for k in topk:
        correct_k = correct[:k].view(-1).float().sum(0)
        res.append(correct_k.mul_(100.0 / batch_size))
    return res


def validate(model, testloader, optimizer, updates):
	#Testing
	loss_vec = numpy.array([])
	batch_time = AverageMeter()
	losses = AverageMeter()
	accs = AverageMeter()
	end = time.time()

	model.eval()

	for batch_idx, (img, target) in enumerate(testloader):
		img = Variable(img, volatile=True).cuda()
		target = Variable(target, volatile=True).cuda(async=True)

		output, _, confidence = model(img)

		# Compute the loss for each sample in the minibatch
		onehot_target = Variable(encode_onehot(target, args.num_classes))
		xentropy_loss_vector = -1 * torch.sum(torch.log(F.softmax(output))
                                                * onehot_target,
                                              dim=1,
                                              keepdim=True)

		# Sum minibatch loss vector
		loss_vec = numpy.append(loss_vec,
								xentropy_loss_vector.data.cpu().numpy())

		xentropy_loss_vector_sum = xentropy_loss_vector.sum()
		xentropy_loss_vector_mean = xentropy_loss_vector.mean()

		#_, predict = torch.max(output, 1)
		#test_accuracy = (target == predict.squeeze()).float().mean()

        # measure accuracy and record loss
		prec1 = accuracy(output.data, target.data, topk=(1,))[0]
		losses.update(xentropy_loss_vector_sum.data[0], img.size(0))
		accs.update(prec1[0], img.size(0))

		#accs.update(test_accuracy.data[0], img.size(0))
		#losses.update(xentropy_loss_vector_sum.data[0], img.size(0))

		# measure elapsed time
		batch_time.update(time.time() - end)
		end = time.time()

		if batch_idx % args.print_freq == 0:
			print('Test: [{0}/{1}]\t'
					'Time {batch_time.val:.3f} ({batch_time.avg:.3f})\t'
					'Loss {loss.val:.4f} ({loss.avg:.4f})\t'
					'Prec@1 {accs.val:.3f} ({accs.avg:.3f})'.format(
						batch_idx, len(testloader), batch_time=batch_time, loss=losses,
						accs=accs))


	# log avg values to somewhere
	#pdb.set_trace()
	#print('\nTest set: Average loss: {:.4f}, Accuracy: {:.2f}%\n'.format(losses.avg, 100. * accs.avg))

	# log avg values to somewhere
	if args.visdom:
		plotter.plot('acc', 'test', updates, accs.avg)
		plotter.plot('loss', 'test', updates, losses.avg)

def train(model, batch_builder, trainloader, trainset, n_train, optimizer, iteration, n_steps, updates, batch_train_inds, confidence_criterion):
	#adjust_learning_rate(optimizer, i+1)
	loss_vec = numpy.array([])
	batch_time = AverageMeter()
	losses = AverageMeter()
	accs = AverageMeter()

	confidence_loss_weighting = 0.1

    # switch to train mode
	model.train()

	#pdb.set_trace()
	end = time.time()
	
	for batch_idx, (img, target) in tqdm(enumerate(trainloader)):
		img = Variable(img).cuda()
		target = Variable(target).cuda(async=True)
		confidence_labels = Variable(torch.ones(target.size())).cuda(async=True)

		optimizer.zero_grad()

		# Get confidence
		output, features, confidence = model(img)
		pdb.set_trace()

		# Compute the loss for each sample in the minibatch
		onehot_target = Variable(encode_onehot(target, args.num_classes))

		pred_conf = output * (0.8 * confidence.expand_as(output) + 0.1) + onehot_target * (1 - (0.8 * confidence.expand_as(onehot_target) + 0.1))
		pred_conf = torch.log(pred_conf)

		xentropy_loss_vector = -1 * torch.sum(torch.log(F.softmax(pred_conf))
                                                            * onehot_target,
                                                        dim=1,
                                                        keepdim=True)

		# Sum minibatch loss vector
		loss_vec = numpy.append(loss_vec,
								xentropy_loss_vector.data.cpu().numpy())
		xentropy_loss_vector_sum = xentropy_loss_vector.sum()
		xentropy_loss_vector_mean = xentropy_loss_vector.mean()

		confidence_loss = confidence_criterion(confidence, confidence_labels)

		if args.budget > confidence_loss.data[0]:
			confidence_loss_weighting = confidence_loss_weighting * 0.98
		elif args.budget <= confidence_loss.data[0]:
			confidence_loss_weighting = confidence_loss_weighting * 1.02

		total_loss = xentropy_loss_vector_mean + confidence_loss * confidence_loss_weighting
		pdb.set_trace()

		# Backward
		total_loss.backward()
		optimizer.step()

		# measure elapsed time
		batch_time.update(time.time() - end)
		end = time.time()

		# measure accuracy and record loss
		prec1 = accuracy(output.data, target.data, topk=(1,))[0]
		losses.update(xentropy_loss_vector_sum.data[0], img.size(0))
		confident_losses.update(confident_loss.data[0], img.size(0))
		accs.update(prec1[0], img.size(0))

		if batch_idx % args.print_freq == 0:
			print('Iteration: [{0}][{1}/{2}]\t'
					'Time {batch_time.val:.3f} ({batch_time.avg:.3f})\t'
					'Loss {loss.val:.4f} ({loss.avg:.4f})\t'
					'Prec@1 {accs.val:.3f} ({accs.avg:.3f})'.format(
					batch_idx, n_steps, len(trainloader), batch_time=batch_time,
					loss=losses, accs=accs))

		# Compute training accuracy
		#_, predict = torch.max(output, 1)

		#train_accuracy = (target == predict.squeeze()).float().mean()

		#losses.update(xentropy_loss_vector_sum.data[0], img.size(0))
		#accs.update(train_accuracy.data[0], img.size(0))

		start = batch_idx * img.size(0)
		stop = start + img.size(0)
		updates += 1
		batch_builder.update_losses(batch_train_inds[start:stop],
								xentropy_loss_vector.squeeze())

	batch_train_inds = batch_builder.gen_batch_spl(spld_params[0], spld_params[1], spld_params[2])

	batch_train_inds = batch_train_inds[0]

	trainloader.sampler.batch_indices = batch_train_inds

	# Increase the learning pace
	spld_params[0] *= (1+spld_params[2])
	spld_params[0] = int(round(spld_params[0]))
	spld_params[1] *= (1+spld_params[3])

	if iteration > 0:
		if args.visdom:
			plotter.plot('acc', 'train', updates, accs.avg)
			plotter.plot('loss', 'train', updates, losses.avg)

	return updates, batch_train_inds

def main(trainloader, trainset, testloader, n_train):

	'''
	TODO:
		1. Set SPLD true/false
		2. If curriculum epoch is 0, cluster then start first update
           with a random minibatch, and the compute loss for all samples
		3. If curriculum epoch is 0, after step 2, determine the next
           minibatch using SPLD
		4. If Curriculum epoch is a multiple of 10 and less than 80,
           refresh the cluster.
	'''
	# Enabled SPLD
	#print(train_idx)

	#exit()
	best_prec1 = 0
	learning_rate = args.lr
	loss_weight = args.loss_weight
	curriculum_rate = args.curriculum_rate
	momentum = numpy.float64(args.momentum)
	decay_after_epochs = args.decay_after_epochs
	tsne_dim = 10
	k = 8
	m = 8
	d = 8

	epoch_steps = int(ceil(len(trainset)) / args.batch_size)
	n_steps = epoch_steps * 15
	#pdb.set_trace()

	global plotter
	plotter = VisdomLinePlotter(env_name=args.name)

	if args.spl:
		print("Start SPLD for LeNet")
		#spld_params = [50, 1e-3, 5e-2, 1e-1]
		global spld_params 
		spld_params = [50, 4e-1, 1e-1, 1e-1]

		prev_mean_all_loss = float('inf')

		if args.mnist:
			model = LeNet()
			model.cuda()
			print(model)

		if args.cifar10:
			classes = ('plane', 'car', 'bird', 'cat', 'deer', 'dog', 'frog', 'horse', 'ship', 'truck')
			#model = PreActResNet18()
			#model = ResNetCifar10()
			#model = GoogLeNet()
			#model = LeNetCifar10()
			#model = Wide_ResNet(28, 10, 0.3, 10)
			model = Wide_ResNet_Conf(28, 10, 0.3, 10)
			model.cuda()
			model = torch.nn.DataParallel(model, device_ids=range(torch.cuda.device_count()))
			cudnn.benchmark = True

			print(model)

		if args.fashionmnist:
			model = FashionLeNet()
			mode.cuda()
			print(model)

		criterion = nn.CrossEntropyLoss(size_average=False)
		confidence_criterion = nn.BCELoss()

		if args.cifar10:
			optimizer = optim.SGD(model.parameters(),
	                              lr=learning_rate,
	                              momentum=momentum,
	                              weight_decay=args.weight_decay)

		if args.mnist:
			optimizer = optim.SGD(model.parameters(),
	                              lr=learning_rate,
	                              momentum=momentum)
		#train_features_seq = extract_features(model,
		#									  n_train,
		#									  trainloader)

		#labels_, cluster_centers, nn_center = group_data(train_features_seq,
		#												 tsne_dim,
		#												 args.num_cluster,
		#												 'mnist',
		#												 save_file=False)

		# Create batcher
		labels = getattr(trainset, 'train_labels')
		#pdb.set_trace()

		initial_reps = compute_reps(model, trainset, 400)

		batch_builder = ClusterBatchBuilder(labels, k, m, d)
		batch_builder.update_clusters(initial_reps)

		#pdb.set_trace()
		losses = AverageMeter()
		accs = AverageMeter()
		batch_losses = []

		#batch_example_inds, batch_class_inds = batch_builder.gen_batch()
		#trainloader.sampler.batch_indices = batch_example_inds
		#pdb.set_trace()

		_ = model.train()
		updates = 0
		for i in tqdm(range(n_steps)):
			if i == 0:
				batch_train_inds = np.arange(len(trainset))
				#pdb.set_trace()
				trainloader.sampler.batch_indices = batch_train_inds

			updates, batch_train_inds = train(model,
						batch_builder,
						trainloader, 
						trainset, 
						n_train, 
						optimizer, 
						i, 
						n_steps, 
						updates,
						batch_train_inds,
						confidence_criterion)

			if i > 0:
				# evaluate on validation set
				prec1 = validate(model, testloader, optimizer, updates)

				# remember best prec@1 and save checkpoint
				is_best = prec1 > best_prec1
				best_prec1 = max(prec1, best_prec1)

				save_checkpoint({
					'epoch': updates + 1,
					'state_dict': model.state_dict(),
					'best_prec1': best_prec1,
				}, is_best)

		print ('Best accuracy: ', best_prec1)

		exit()
		# for i in tqdm(range(n_steps)):

		# 	losses = AverageMeter()
		# 	accs = AverageMeter()
			
		# 	#pdb.set_trace()
		# 	if i == 0:
		# 		batch_train_inds = np.arange(len(trainset))
		# 		#pdb.set_trace()
		# 		trainloader.sampler.batch_indices = batch_train_inds

		# 	#else:
		# 	#	train_sampler = SubsetSequentialSamplerSPLDML(range(len(trainset)), range(len(batch_train_inds)))
		# 	#	trainloader = DataLoader(trainset,
		# 	#					 batch_size=4,
		# 	#					 shuffle=False,
		# 	#					 num_workers=1,
		# 	#					 sampler=train_sampler)

		# 	'''
		# 	if i > 0:
		# 		print("Start self-paced learning with diversity")
		# 		train_idx = numpy.array([])

		# 		for i in range(args.num_cluster):
		# 			i_cluster = numpy.where(labels_ == i)[0]
		# 			iloss_vec = loss_vec[i_cluster]
		# 			#pdb.set_trace()
		# 			#print(iloss_vec)
		# 			sortIndex = numpy.argsort(iloss_vec)
		# 			#print(sortIndex)
		# 			#print(iloss_vec[sortIndex])
		# 			#exit()
		# 			#print(iloss_vec)
		# 			#iloss_vec = min_max_sort(iloss_vec, len(iloss_vec))
		# 			#print(iloss_vec)
		# 			#exit()

		# 			#iloss_vec -= spld_params[1] * \
		# 			#						numpy.divide(1,
		# 			#									numpy.sqrt(range(1, 1+len(i_cluster)))
	 #                #                           + numpy.sqrt(range(len(i_cluster))))

		# 			iloss_vec[sortIndex] -= spld_params[1] * \
		# 									numpy.divide(1,
		# 												numpy.sqrt(range(1, 1+len(i_cluster)))
	 #                                            + numpy.sqrt(range(len(i_cluster))))

		# 			#exit()
		# 			K = min([spld_params[0], len(iloss_vec)])
		# 			train_idx = numpy.append(train_idx,
	 #                                         i_cluster[numpy.argpartition(iloss_vec, K-1)[:K]])

		# 		train_idx = train_idx.astype('int32')

		# 		# Increase the learning pace
		# 		spld_params[0] *= (1 + spld_params[2])
		# 		spld_params[0] = int(round(spld_params[0]))
		# 		spld_params[1] *= (1 + spld_params[3])	

		# 		print("Finished SPLD")

		# 		trainloader.sampler.batch_indices = train_idx
		# 		pdb.set_trace()
		# 		loss_vec = numpy.array([])
		# 	'''

		# 	for batch_idx, (img, target) in tqdm(enumerate(trainloader)):
		# 		img = Variable(img).cuda()
		# 		target = Variable(target).cuda()

		# 		optimizer.zero_grad()
		# 		output, features = model(img)

		# 		# Compute the loss for each sample in the minibatch
		# 		onehot_target = Variable(encode_onehot(target, args.num_classes))
		# 		xentropy_loss_vector = -1 * torch.sum(torch.log(F.softmax(output))
  #                                                                   * onehot_target,
  #                                                               dim=1,
  #                                                               keepdim=True)

		# 		# Sum minibatch loss vector
		# 		loss_vec = numpy.append(loss_vec,
		# 								xentropy_loss_vector.data.cpu().numpy())
		# 		xentropy_loss_vector_sum = xentropy_loss_vector.sum()
		# 		xentropy_loss_vector_mean = xentropy_loss_vector.mean()

		# 		# Backward
		# 		xentropy_loss_vector_sum.backward()
		# 		optimizer.step()

		# 		# Compute training accuracy
		# 		_, predict = torch.max(output, 1)

		# 		train_accuracy = (target == predict.squeeze()).float().mean()

		# 		losses.update(xentropy_loss_vector_sum.data[0], img.size(0))
		# 		accs.update(train_accuracy.data[0], img.size(0))

		# 		'''
		# 		if batch_idx % args.log_interval == 0:
		# 			print('Train Epoch: {} [{}/{}]\t'
		# 					'Loss: {:.4f} ({:.4f}) \t'
		# 					'Acc: {:.2f}% ({:.2f}%) \t'.format(i,
  #                                                               batch_idx * len(img),
  #                                                               len(trainset),
  #                                                               losses.val, losses.avg,
  #                                                               100. * accs.val,
  #                                                               100. * accs.avg))
		# 		'''
		# 		#pdb.set_trace()
		# 	#pdb.set_trace()

		# 		#if i == 0:
		# 		start = batch_idx * img.size(0)
		# 		stop = start + img.size(0)

		# 		#if i > 0:
		# 		#	pdb.set_trace()
		# 		#print(img.size())
		# 		batch_builder.update_losses(batch_train_inds[start:stop],
		# 								xentropy_loss_vector.squeeze())

		# 	#batch_builder.update_losses(batch_example_inds,
		# 	#							xentropy_loss_vector.squeeze())
		# 	#batch_losses.append(xentropy_loss_vector_mean.data[0])
		# 	#pdb.set_trace()
		# 	batch_train_inds = batch_builder.gen_batch_spl(spld_params[0], spld_params[1], spld_params[2])
		# 	#batch_example_inds, batch_class_inds = batch_builder.gen_batch()
		# 	#pdb.set_trace()
		# 	batch_train_inds = batch_train_inds[0]

		# 	trainloader.sampler.batch_indices = batch_train_inds
		# 	#pdb.set_trace()
		# 	# Increase the learning pace

		# 	spld_params[0] *= (1+spld_params[2])
		# 	spld_params[0] = int(round(spld_params[0]))
		# 	spld_params[1] *= (1+spld_params[3])

		# 	#spld_params[0] *= (1 + spld_params[2])
		# 	#spld_params[0] = int(round(spld_params[0]))
		# 	#spld_params[1] *= (1 + spld_params[3])
		# 	#spld_params[0] = int(round(spld_params[0]))
		# 	#spld_params[1] *= (1 + spld_params[3])

		# 	#if not i % 1000:
		# 	#	print("Refreshing clusters")
		# 	#	reps = compute_reps(model, trainset, 400)
		# 	#	batch_builder.update_clusters(reps)

		# 	# log avg values to somewhere
		# 	# losses.update(xentropy_loss_vector_sum.data[0], img.size(0))
		# 	# accs.update(train_accuracy.data[0], img.size(0))

		# 	if i > 0:
		# 		if args.visdom:
		# 			plotter.plot('acc', 'train', i, accs.avg)
		# 			plotter.plot('loss', 'train', i, losses.avg)

		# 		if i % 20 == 0:
		# 			#Testing
		# 			correct_cnt = 0
		# 			ave_loss = 0
		# 			losses = AverageMeter()
		# 			accs = AverageMeter()

		# 			for batch_idx, (img, target) in enumerate(testloader):
		# 				img = Variable(img).cuda()
		# 				target = Variable(target).cuda()

		# 				score, _ = model(img)

		# 				# Compute the loss for each sample in the minibatch
		# 				onehot_target = Variable(encode_onehot(target, args.num_classes))
		# 				xentropy_loss_vector = -1 * torch.sum(torch.log(F.softmax(score))
		# 	                                                    * onehot_target,
		# 	                                                  dim=1,
		# 	                                                  keepdim=True)

		# 				# Sum minibatch loss vector
		# 				loss_vec = numpy.append(loss_vec,
		# 										xentropy_loss_vector.data.cpu().numpy())

		# 				xentropy_loss_vector_sum = xentropy_loss_vector.sum()
		# 				xentropy_loss_vector_mean = xentropy_loss_vector.mean()

		# 				_, predict = torch.max(score, 1)
		# 				test_accuracy = (target == predict.squeeze()).float().mean()

		# 			accs.update(test_accuracy.data[0], img.size(0))
		# 			losses.update(xentropy_loss_vector_sum.data[0], img.size(0))

		# 			# log avg values to somewhere
		# 			#pdb.set_trace()
		# 			print('\nTest set: Average loss: {:.4f}, Accuracy: {:.2f}%\n'.format(losses.avg, 100. * accs.avg))

		# 			# log avg values to somewhere
		# 			if args.visdom:
		# 				plotter.plot('acc', 'test', i, accs.avg)
		# 				plotter.plot('loss', 'test', i, losses.avg)


				#if i % 10 == 0:
				#	print("Refreshing clusters")
				#	reps = compute_reps(model, trainset, 400)
				#	batch_builder.update_clusters(reps)

			# if i % 10 == 0:
			# 	adjust_learning_rate(optimizer, i, learning_rate)

		'''
			if i % args.log_interval == 0:
				print('Train Epoch: {} [{}/{}]\t'
						'Loss: {:.4f} ({:.4f}) \t'
						'Acc: {:.2f}% ({:.2f}%) \t'.format(i,
                                                            i,
                                                            n_steps,
                                                            losses.val, losses.avg,
                                                            100. * accs.val,
                                                            100. * accs.avg))

				_ = model.eval()

				# Testing
				correct_cnt = 0
				ave_loss = 0
				losses = AverageMeter()
				accs = AverageMeter()

				for batch_idx, (img, target) in enumerate(testloader):
					img = Variable(img).cuda()
					target = Variable(target).cuda()

					score, _ = model(img)

					# Compute the loss for each sample in the minibatch
					onehot_target = Variable(encode_onehot(target, args.num_classes))
					xentropy_loss_vector = -1 * torch.sum(torch.log(F.softmax(score))
		                                                    * onehot_target,
		                                                  dim=1,
		                                                  keepdim=True)

					# Sum minibatch loss vector
					loss_vec = numpy.append(loss_vec,
											xentropy_loss_vector.data.cpu().numpy())

					xentropy_loss_vector_sum = xentropy_loss_vector.sum()
					xentropy_loss_vector_mean = xentropy_loss_vector.mean()

					_, predict = torch.max(score, 1)
					test_accuracy = (target == predict.squeeze()).float().mean()

				accs.update(test_accuracy.data[0], img.size(0))
				losses.update(xentropy_loss_vector_sum.data[0], img.size(0))

				# log avg values to somewhere
				#pdb.set_trace()
				print('\nTest set: Average loss: {:.4f}, Accuracy: {:.2f}%\n'.format(losses.avg, 100. * accs.avg))

				# log avg values to somewhere
				if args.visdom:
					plotter.plot('acc', 'test', i, accs.avg)
					plotter.plot('loss', 'test', i, losses.avg)
		'''
		'''
		# Testing
		correct_cnt = 0
		ave_loss = 0
		losses = AverageMeter()
		accs = AverageMeter()

		for batch_idx, (img, target) in enumerate(testloader):
			img = Variable(img).cuda()
			target = Variable(target).cuda()

			score, _ = model(img)

			# Compute the loss for each sample in the minibatch
			onehot_target = Variable(encode_onehot(target, args.num_classes))
			xentropy_loss_vector = -1 * torch.sum(torch.log(F.softmax(score))
                                                    * onehot_target,
                                                  dim=1,
                                                  keepdim=True)

			# Sum minibatch loss vector
			loss_vec = numpy.append(loss_vec,
									xentropy_loss_vector.data.cpu().numpy())

			xentropy_loss_vector_sum = xentropy_loss_vector.sum()
			xentropy_loss_vector_mean = xentropy_loss_vector.mean()

			_, predict = torch.max(score, 1)
			test_accuracy = (target == predict.squeeze()).float().mean()

			accs.update(test_accuracy.data[0], img.size(0))
			losses.update(xentropy_loss_vector_sum.data[0], img.size(0))

		# log avg values to somewhere
		pdb.set_trace()
		print('\nTest set: Average loss: {:.4f}, Accuracy: {:.2f}%\n'.format(losses.avg, 100. * accs.avg))
		'''
		exit()



		'''
		OLD STUFF
		'''
		for curriculum_epoch in tqdm(range(args.curriculum_epochs)):
			running_loss = 0.
			running_acc = 0
			start_idx = 0

			losses = AverageMeter()
			accs = AverageMeter()

			if curriculum_epoch == 0:
				print('Generating cluster classification on training data ...')
				#train_results = compute_clusters(trainloader, model, len(range(args.num_classes)), args.feature_size)

				#print(train_idx)
				print("First curriculum epoch")

				train_features_seq = extract_features(model,
                                                      n_train,
                                                      trainloader)

				labels_, cluster_centers, nn_center = group_data(train_features_seq,
                                                                 10,
                                                                 args.num_cluster,
                                                                 'mnist',
                                                                 save_file=False)

				#labels_, labels_weight, cluster_centers, nn_center = get_cluster(train_features_seq,
				#																 100,
				#																 args.num_cluster,
				#																 'mnist',
				#																 save_file=False)
				#labels_ = labels_.astype('int32')
				#nn_center = nn_center.astype('int32')
				#print(labels_weight)
				#exit()
				#plot_kmeans_hist(labels_, bins=args.num_cluster)
				#print(trainloader)
				#exit()

			loss_vec = numpy.array([])
			losses = AverageMeter()
			accs = AverageMeter()
			for batch_idx, (img, target) in enumerate(trainloader):
				#print("Batch idx: {}".format(batch_idx))
				img = Variable(img).cuda()
				target = Variable(target).cuda()

				optimizer.zero_grad()
				output, _ = model(img)

				# Compute the loss for each sample in the minibatch
				onehot_target = Variable(encode_onehot(target, args.num_classes))
				xentropy_loss_vector = -1 * torch.sum(torch.log(F.softmax(output))
                                                                    * onehot_target,
                                                                dim=1,
                                                                keepdim=True)

				# Sum minibatch loss vector
				loss_vec = numpy.append(loss_vec,
										xentropy_loss_vector.data.cpu().numpy())
				xentropy_loss_vector_sum = xentropy_loss_vector.sum()
				xentropy_loss_vector_mean = xentropy_loss_vector.mean()

				losses.update(xentropy_loss_vector_sum.data[0], img.size(0))

				# Backward
				xentropy_loss_vector_sum.backward()
				optimizer.step()
				#print(xentropy_loss_vector_sum)

				# Compute training accuracy
				_, predict = torch.max(output, 1)

				train_accuracy = (target == predict.squeeze()).float().mean()
				accs.update(train_accuracy.data[0], img.size(0))

				if batch_idx % args.log_interval == 0:
					print('Train Epoch: {} [{}/{}]\t'
							'Loss: {:.4f} ({:.4f}) \t'
							'Acc: {:.2f}% ({:.2f}%) \t'.format(curriculum_epoch+1,
                                                                batch_idx * len(img),
                                                                len(trainset),
                                                                losses.val, losses.avg,
                                                                100. * accs.val,
                                                                100. * accs.avg))


			# log avg values to somewhere
			if args.visdom:
				plotter.plot('acc', 'train', curriculum_epoch+1, accs.avg)
				plotter.plot('loss', 'train', curriculum_epoch+1, losses.avg)

			# Compute the mean loss
			#print(len(loss_vec))
			curr_mean_all_loss = numpy.mean(loss_vec)
			#print('mean training loss = ', curr_mean_all_loss)


			# Self-paced learning with diversity sampling
			# Selecting samples using the self-paced learning with diversity
			# update clustering and submodular function F
			#if epoch % args.fea_freq == 0:

			train_idx = numpy.array([])

			print("Start self-paced learning with diversity")
			#select sample: self-paced learning with diversity
			#print(loss_vec)
			#print(len(loss_vec))
			train_idx = numpy.array([])
			#print(len(loss_vec))
			#for i in loss_vec:
			#	print(i)
			#exit()

			for i in range(args.num_cluster):
				i_cluster = numpy.where(labels_ == i)[0]
				#pdb.set_trace()
				#print(i_cluster)
				#exit()
				iloss_vec = loss_vec[i_cluster]
				#pdb.set_trace()
				#print(iloss_vec)
				#sortIndex = numpy.argsort(iloss_vec)
				#print(sortIndex)
				#print(iloss_vec[sortIndex])
				#exit()
				#print(iloss_vec)
				#iloss_vec = min_max_sort(iloss_vec, len(iloss_vec))
				#print(iloss_vec)
				#exit()

				iloss_vec -= spld_params[1] * \
										numpy.divide(1,
													numpy.sqrt(range(1, 1+len(i_cluster)))
                                            + numpy.sqrt(range(len(i_cluster))))
				'''
				iloss_vec[sortIndex] -= spld_params[1] * \
										numpy.divide(1,
													numpy.sqrt(range(1, 1+len(i_cluster)))
                                            + numpy.sqrt(range(len(i_cluster))))

				'''
				#exit()
				K = min([spld_params[0], len(iloss_vec)])
				train_idx = numpy.append(train_idx,
                                         i_cluster[numpy.argpartition(iloss_vec, K-1)[:K]])

			train_idx = train_idx.astype('int32')

			# Increase the learning pace
			spld_params[0] *= (1 + spld_params[2])
			spld_params[0] = int(round(spld_params[0]))
			spld_params[1] *= (1 + spld_params[3])
			#print(train_idx)
			#print(len(train_idx))

			#decay_after_epochs = 3
			#if (curriculum_epoch + 1) % decay_after_epochs == 0:
			#print(prev_mean_all_loss)

			'''
				TODO: update learning rate and learning pace
				TODO: Update clustering
			'''
			'''
			if curr_mean_all_loss > 1.005 * prev_mean_all_loss:
				learning_rate *= 0.95
				optimizer.param_groups[0]['lr'] = learning_rate
				momentum_update = (1.0 - (1.0 - momentum) * 0.95).clip(max=0.9999)
				optimizer.param_groups[0]['momentum'] = momentum_update
			'''
        	# update learning rate and learning pace
			if curriculum_epoch % args.lr_freq == 0:
				adjust_learning_rate(optimizer, curriculum_epoch, learning_rate)
            	#loss_weight *= curriculum_rate + 1
            	#print ('loss_weight, num_learner_per_cluster', args.loss_weight, args.num_learner_per_cluster)

			# update clustering
			#if curriculum_epoch % args.fea_freq == 0:
				 # clustering
			#	train_features_seq = extract_features(model,
            #                                          n_train,
            #                                          trainloader)
			#	labels_, cluster_centers, nn_center = group_data(train_features_seq,
            #                                                     10,
            #                                                     args.num_cluster,
            #                                                     'mnist',
            #                                                     save_file=False)

			print("Finished SPLD")

			#print(prev_mean_all_loss)
			#if curr_mean_all_loss > 1.005 * prev_mean_all_loss:
			#	learning_rate *= 0.96
			#	print(prev_mean_all_loss)
			#	print(curr_mean_all_loss)
			#	print(learning_rate)
			#	optimizer.param_groups[0]['lr'] = learning_rate

			prev_mean_all_loss = curr_mean_all_loss

			#print(len(trainloader.sampler.indices))
			#trainloader.sampler.indices = list(range(0, 60000))
			trainloader.sampler.indices = train_idx
			#print(len(trainloader.sampler.indices))
			#print(optimizer.param_groups[0]['lr'])

			# Testing
			correct_cnt = 0
			ave_loss = 0
			losses = AverageMeter()
			accs = AverageMeter()

			for batch_idx, (img, target) in enumerate(testloader):
				img = Variable(img).cuda()
				target = Variable(target).cuda()

				score, _ = model(img)

				# Compute the loss for each sample in the minibatch
				onehot_target = Variable(encode_onehot(target, args.num_classes))
				xentropy_loss_vector = -1 * torch.sum(torch.log(F.softmax(score))
                                                        * onehot_target,
                                                      dim=1,
                                                      keepdim=True)

				# Sum minibatch loss vector
				loss_vec = numpy.append(loss_vec,
										xentropy_loss_vector.data.cpu().numpy())

				xentropy_loss_vector_sum = xentropy_loss_vector.sum()
				xentropy_loss_vector_mean = xentropy_loss_vector.mean()

				_, predict = torch.max(score, 1)
				test_accuracy = (target == predict.squeeze()).float().mean()

				accs.update(test_accuracy.data[0], img.size(0))
				losses.update(xentropy_loss_vector_sum.data[0], img.size(0))

			# log avg values to somewhere
			print('\nTest set: Average loss: {:.4f}, Accuracy: {:.2f}%\n'.format(losses.avg, 100. * accs.avg))
			if args.visdom:
				plotter.plot('acc', 'test', curriculum_epoch+1, accs.avg)
				plotter.plot('loss', 'test', curriculum_epoch+1, losses.avg)

		torch.save(model.state_dict(), model.name())

	else:
		if args.mnist:
			model = LeNet()
			print(model)

		if args.cifar10:
			classes = ('plane', 'car', 'bird', 'cat', 'deer', 'dog', 'frog', 'horse', 'ship', 'truck')
			#model = PreActResNet18()
			model = ResNetCifar10()
			print(model)

		if args.fashionmnist:
			model = FashionLeNet()
			print(model)


		model.cuda()

		criterion = nn.CrossEntropyLoss(size_average=False)
		optimizer = optim.SGD(model.parameters(),
                              lr=learning_rate,
                              momentum=momentum)

		for epoch in range(args.epochs):
			running_loss = 0.
			running_acc = 0.
			losses = AverageMeter()
			accs = AverageMeter()
			model.train()
			for batch_idx, (img, target) in tqdm(enumerate(trainloader)):
				img = Variable(img).cuda()
				target = Variable(target).cuda()

				optimizer.zero_grad()
				output, _ = model(img)

				loss = criterion(output, target)

				#loss_mean = loss.mean()

				losses.update(loss.data[0], img.size(0))

				loss.backward()
				optimizer.step()

				_, predict = torch.max(output, 1)
				train_accuracy = (target == predict.squeeze()).float().mean()

				accs.update(train_accuracy.data[0], img.size(0))

				if batch_idx % args.log_interval == 0:
					print('Train Epoch: {} [{}/{}]\t'
							'Loss: {:.4f} ({:.4f}) \t'
							'Acc: {:.2f}% ({:.2f}%) \t'.format(epoch+1,
                                                               batch_idx * len(img),
                                                               len(trainset),
                                                               losses.val, losses.avg,
                                                               100. * accs.val,
                                                               100. * accs.avg))

			# log avg values to somewhere
			if args.visdom:
				plotter.plot('acc', 'train', epoch+1, accs.avg)
				plotter.plot('loss', 'train', epoch+1, losses.avg)

			# Testing
			model.eval()

			losses = AverageMeter()
			accs = AverageMeter()
			for batch_idx, (img, target) in enumerate(testloader):
				# volatile=True is used in inference mode. it makes stopping histoy recording for backward().
				img = Variable(img, volatile=True).cuda()
				target = Variable(target).cuda()

				score, _ = model(img)

				loss = criterion(score, target)
				#loss_mean = loss.mean()

				_, predict = torch.max(score, 1)

				test_accuracy = (target == predict.squeeze()).float().mean()

				accs.update(test_accuracy.data[0], img.size(0))
				losses.update(loss.data[0], img.size(0))

			# log avg values to somewhere
			print('\nTest set: Average loss: {:.4f}, Accuracy: {:.2f}%\n'.format(losses.avg, 100. * accs.avg))
			if args.visdom:
				plotter.plot('acc', 'test', epoch+1, accs.avg)
				plotter.plot('loss', 'test', epoch+1, losses.avg)

		torch.save(model.state_dict(), model.name())

if __name__ == '__main__':
	"""
	TODO:
		Train on a larger dataset, MNIST Fashion, tiny imagenet
		Fix KMeans
		Try different CNN model
		Ensemble curriculum learning
		Integrate Magnet Loss
	"""
	trainloader, testloader, trainset, testset, n_train = load_dataset(args)
	n_train_batches = len(trainset) // args.batch_size
	n_test_batches =  len(testset) // args.batch_size

	print("==>>> Total Training Batch Number: {}".format(len(trainset)))
	print("==>>> Total Number of Train Batches: {}".format(n_train_batches))
	print("==>>> Total Number of Test Batches: {}".format(n_test_batches))

	print("Starting Training...")
	main(trainloader, trainset, testloader, n_train)