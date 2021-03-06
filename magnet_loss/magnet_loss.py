# Copyright 2018 Vithursan Thangarasa.
#
# This file is part of SPL-ADVisE.
#
# SPL-ADVisE is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.
#
# SPL-ADVisE is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# SPL-ADVisE. If not, see <http://www.gnu.org/licenses/>.

import torch
import torch.nn as nn
from torch.autograd import Variable
import torch.nn.functional as F

import numpy as np
import pdb

GPU_INT_DTYPE = torch.cuda.IntTensor
GPU_LONG_DTYPE = torch.cuda.LongTensor
GPU_FLOAT_DTYPE = torch.cuda.FloatTensor

INT_DTYPE = torch.IntTensor
LONG_DTYPE = torch.LongTensor
FLOAT_DTYPE = torch.FloatTensor

class MagnetLoss(nn.Module):
	def __init__(self, alpha=1.0, device='cpu'):
		super(MagnetLoss, self).__init__()
		self.r = None
		self.classes = None
		self.clusters = None
		self.cluster_classes = None
		self.n_clusters = None
		self.alpha = alpha
		self.device = device

	def forward(self, r, classes, m, d, alpha=1.0):

		self.r = r

		if self.device == 'cuda':
			self.classes = torch.from_numpy(classes).type(GPU_LONG_DTYPE)
			self.clusters, _ = torch.sort(torch.arange(0, float(m)).repeat(d))
			self.clusters = self.clusters.type(GPU_INT_DTYPE)
		else:
			self.classes = torch.from_numpy(classes).type(LONG_DTYPE)
			self.clusters, _ = torch.sort(torch.arange(0, float(m)).repeat(d))
			self.clusters = self.clusters.type(INT_DTYPE)

		self.cluster_classes = self.classes[0:m*d:d]
		self.n_clusters = m
		self.alpha = alpha
		#pdb.set_trace()

		# Take cluster means within the batch
		cluster_examples = dynamic_partition(self.r, self.clusters, self.n_clusters)
		#pdb.set_trace()

		cluster_means = torch.stack([torch.mean(x, dim=0) for x in cluster_examples])
		#pdb.set_trace()

		sample_costs = compute_euclidean_distance(cluster_means, expand_dims(r, 1))
		#pdb.set_trace()

		if self.device == 'cuda':
			clusters_tensor = self.clusters.type(GPU_FLOAT_DTYPE)
			n_clusters_tensor = torch.arange(0, self.n_clusters).type(GPU_FLOAT_DTYPE)
			intra_cluster_mask = Variable(comparison_mask(clusters_tensor, n_clusters_tensor).type(GPU_FLOAT_DTYPE))
		else:
			clusters_tensor = self.clusters.type(FLOAT_DTYPE)
			n_clusters_tensor = torch.arange(0, self.n_clusters).type(FLOAT_DTYPE)
			intra_cluster_mask = Variable(comparison_mask(clusters_tensor, n_clusters_tensor).type(FLOAT_DTYPE))
		#pdb.set_trace()

		#pdb.set_trace()

		intra_cluster_costs = torch.sum(intra_cluster_mask * sample_costs, dim=1)
		#pdb.set_trace()

		N = r.size()[0]
		#pdb.set_trace()

		variance = torch.sum(intra_cluster_costs) / float(N - 1)
		#pdb.set_trace()

		var_normalizer = -1 / (2 * variance**2)
		#pdb.set_trace()

		# Compute numerator
		numerator = torch.exp(var_normalizer * intra_cluster_costs - self.alpha)
		#pdb.set_trace()

		if self.device == 'cuda':
			classes_tensor = self.classes.type(GPU_FLOAT_DTYPE)
			cluster_classes_tensor = self.cluster_classes.type(GPU_FLOAT_DTYPE)
			# Compute denominator
			diff_class_mask = Variable(comparison_mask(classes_tensor, cluster_classes_tensor).type(GPU_FLOAT_DTYPE))
		else:
			classes_tensor = self.classes.type(FLOAT_DTYPE)
			cluster_classes_tensor = self.cluster_classes.type(FLOAT_DTYPE)
			# Compute denominator
			diff_class_mask = Variable(comparison_mask(classes_tensor, cluster_classes_tensor).type(FLOAT_DTYPE))

		diff_class_mask = 1 - diff_class_mask # Logical not on ByteTensor
		#pdb.set_trace()

		denom_sample_costs = torch.exp(var_normalizer * sample_costs)
		#pdb.set_trace()

		denominator = torch.sum(diff_class_mask * denom_sample_costs, dim=1)
		#pdb.set_trace()

		epsilon = 1e-8
		#pdb.set_trace()

		losses = F.relu(-torch.log(numerator / (denominator + epsilon) + epsilon))
		#pdb.set_trace()

		total_loss = torch.mean(losses)
		#pdb.set_trace()

		return total_loss, losses		

def expand_dims(var, dim=0):
	""" Is similar to [numpy.expand_dims](https://docs.scipy.org/doc/numpy/reference/generated/numpy.expand_dims.html).
		var = torch.range(0, 9).view(-1, 2)
		torch.expand_dims(var, 0).size()
		# (1, 5, 2)
	"""
	sizes = list(var.size())
	sizes.insert(dim, 1)
	return var.view(*sizes)

def comparison_mask(a_labels, b_labels):
	return torch.eq(expand_dims(a_labels, 1), 
					expand_dims(b_labels, 0))

def dynamic_partition(X, partitions, n_clusters):
	cluster_bin = torch.chunk(X, n_clusters)
	return cluster_bin

def compute_euclidean_distance(x, y):
	return torch.sum((x - y)**2, dim=2)