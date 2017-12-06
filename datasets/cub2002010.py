# from __future__ import print_function
# import os
# import errno
# import torch
# import numpy as np
# from PIL import Image
# import torch.utils.data as data
# import scipy
# import pdb
#
# class CUB2002010(data.Dataset):
#     """`CUB200-2010 <http://www.vision.caltech.edu/visipedia/CUB-200.html>`_ Dataset.
#     Args:
#         root (string): Root directory of dataset where ``processed/training.pt``
#             and  ``processed/test.pt`` exist.
#         train (bool, optional): If True, creates dataset from ``training.pt``,
#             otherwise from ``test.pt``.
#         download (bool, optional): If true, downloads the dataset from the internet and
#             puts it in root directory. If dataset is already downloaded, it is not
#             downloaded again.
#         transform (callable, optional): A function/transform that  takes in an PIL image
#             and returns a transformed version. E.g, ``transforms.RandomCrop``
#         target_transform (callable, optional): A function/transform that takes in the
#             target and transforms it.
#     """
#     urls = [
#         'http://www.vision.caltech.edu/visipedia-data/CUB-200/images.tgz',
#         'http://www.vision.caltech.edu/visipedia-data/CUB-200/lists.tgz'
#     ]
#     raw_folder = 'raw'
#     processed_folder = 'processed'
#     training_file = 'training.pt'
#     test_file = 'test.pt'
#
#     def __init__(self, root, train=True, transform=None, target_transform=None, download=False):
#         self.root = os.path.expanduser(root)
#         self.transform = transform
#         self.target_transform = target_transform
#         self.train = train
#
#         if download:
#             self.download()
#
#         if not self._check_exists():
#             raise RuntimeError('Dataset not found. You can use download=True to download it')
#
#         if self.train:
#             self.train_data, self.train_labels = torch.load(
#                 os.path.join(self.root, self.processed_folder, self.training_file))
#         else:
#             self.test_data, self.test_labels = torch.load(
#                 os.path.join(self.root, self.processed_folder, self.test_file))
#         pdb.set_trace()
#     def __getitem__(self, index):
#         """
#         Args:
#             index (int): Index
#         Returns:
#             tuple: (image, target) where target is index of the target class.
#         """
#         if self.train:
#             img, target = self.train_data[index], self.train_labels[index]
#         else:
#             img, target = self.test_data[index], self.test_labels[index]
#
#         #pdb.set_trace()
#         #print(img.shape)
#         img = Image.fromarray(img.numpy(), mode='RGB')
#         #print(img.shape)
#
#         if self.transform is not None:
#             img = self.transform(img)
#
#         if self.target_transform is not None:
#             img = self.target_transform(img)
#
#         return img, target
#
#     def __len__(self):
#         if self.train:
#             return len(self.train_data)
#         else:
#             return len(self.test_data)
#
#     def _check_exists(self):
#         return os.path.exists(os.path.join(self.root, self.processed_folder, self.training_file))
#
#     def download(self):
#         from six.moves import urllib
#         import tarfile
#
#         if self._check_exists():
#             return
#
#         try:
#             os.makedirs(os.path.join(self.root, self.raw_folder))
#             os.makedirs(os.path.join(self.root, self.processed_folder))
#         except OSError as e:
#             if e.errno == errno.EEXIST:
#                 pass
#             else:
#                 raise
#
#         for url in self.urls:
#             print('Downloading ' + url)
#             data = urllib.request.urlopen(url)
#             filename = url.rpartition('/')[2]
#             file_path = os.path.join(self.root, self.raw_folder, filename)
#             with open(file_path, 'wb') as f:
#                 f.write(data.read())
#             tar = tarfile.open(file_path, 'r')
#             for item in tar:
#                 tar.extract(item, file_path.replace(filename, ''))
#             os.unlink(file_path)
#
#         print('Processing...')
#
#         images_file_path = os.path.join(self.root, self.raw_folder, 'images/')
#         tr_lists_file_path = os.path.join(self.root, self.raw_folder, 'lists/train.txt')
#         te_lists_file_path = os.path.join(self.root, self.raw_folder, 'lists/test.txt')
#
#         train_files = np.genfromtxt(tr_lists_file_path, dtype=str)
#         test_files = np.genfromtxt(te_lists_file_path, dtype=str)
#         train_data = []
#         test_data = []
#         train_labels = []
#         test_labels = []
#         for name in train_files:
#             pathway = os.path.join(images_file_path, name)
#             img = Image.open(pathway)
#             img = img.resize((64, 64), Image.ANTIALIAS)
#             npimg = np.array(img.getdata()).astype(float)
#             npimg = np.reshape(npimg, (img.size[0], img.size[1], 3))
#             npimg = np.transpose(npimg, (2, 0, 1))
#             train_data.append(npimg)
#             train_labels.append(int(name[0:3]) - 1)
#             img.close()
#
#         for name in test_files:
#             pathway = os.path.join(images_file_path, name)
#             img = Image.open(pathway)
#             img = img.resize((64, 64), Image.ANTIALIAS)
#             npimg = np.array(img.getdata()).astype(float)
#             npimg = np.reshape(npimg, (img.size[0], img.size[1], 3))
#             npimg = np.transpose(npimg, (2, 0, 1))
#             test_data.append(npimg)
#             test_labels.append(int(name[0:3]) - 1)
#             img.close()
#
#         train_data = np.array(train_data) / 255
#         train_labels = np.array(train_labels)
#         test_data = np.array(test_data) / 255
#         test_labels = np.array(test_labels)
#
#         assert train_data.shape[0] == 3000 and test_data.shape[0] == 3033
#         assert train_labels.shape[0] == 3000 and test_labels.shape[0] == 3033
#
#         training_set = (
#             torch.from_numpy(train_data).type(torch.FloatTensor),
#             torch.from_numpy(train_labels).type(torch.LongTensor)
#         )
#         testing_set = (
#             torch.from_numpy(test_data).type(torch.FloatTensor),
#             torch.from_numpy(test_labels).type(torch.LongTensor)
#         )
#
#         torch.save(training_set, os.path.join(self.root, self.processed_folder, self.training_file))
#         torch.save(testing_set, os.path.join(self.root, self.processed_folder, self.test_file))
#
#         print('Done!')


from __future__ import print_function
import os
import errno
import torch
import numpy as np
from PIL import Image
import torch.utils.data as data


def pil_loader(path):
    with open(path, 'rb') as f:
        with Image.open(f) as img:
            return img.convert('RGB')


def accimage_loader(path):
    import accimage
    try:
        return accimage.Image(path)
    except IOError:
        return pil_loader(path)


def default_loader(path):
    from torchvision import get_image_backend
    if get_image_backend() == 'accimage':
        return accimage_loader(path)
    else:
        return pil_loader(path)


def build_set(root, year, train):
    """
       Function to return the lists of paths with the corresponding labels for the images
    Args:
        root (string): Root directory of dataset
        year (int): Year/version of the dataset. Available options are 2010 and 2011
        train (bool, optional): If true, returns the list pertaining to training images and labels, else otherwise
    Returns:
        return_list: list of 2-tuples with 1st location specifying path and 2nd location specifying the class
    """
    if year == 2010:
        images_file_path = os.path.join(root, 'images/')

        if train:
            lists_path = os.path.join(root, 'lists/train.txt')
        else:
            lists_path = os.path.join(root, 'lists/test.txt')

        files = np.genfromtxt(lists_path, dtype=str)

        imgs = []
        classes = []
        class_to_idx = []

        for fname in files:
            full_path = os.path.join(images_file_path, fname)
            imgs.append((full_path, int(fname[0:3]) - 1))
            if os.path.split(fname)[0][4:] not in classes:
                classes.append(os.path.split(fname)[0][4:])
                class_to_idx.append(int(fname[0:3]) - 1)

        return imgs, classes, class_to_idx

    elif year == 2011:
        images_file_path = os.path.join(root, 'CUB_200_2011/images/')

        all_images_list_path = os.path.join(root, 'CUB_200_2011/images.txt')
        all_images_list = np.genfromtxt(all_images_list_path, dtype=str)
        train_test_list_path = os.path.join(root, 'CUB_200_2011/train_test_split.txt')
        train_test_list = np.genfromtxt(train_test_list_path, dtype=int)

        imgs = []
        classes = []
        class_to_idx = []

        for i in range(0, len(all_images_list)):
            fname = all_images_list[i, 1]
            full_path = os.path.join(images_file_path, fname)
            if train_test_list[i, 1] == 1 and train:
                imgs.append((full_path, int(fname[0:3]) - 1))
            elif train_test_list[i, 1] == 0 and not train:
                imgs.append((full_path, int(fname[0:3]) - 1))
            if os.path.split(fname)[0][4:] not in classes:
                classes.append(os.path.split(fname)[0][4:])
                class_to_idx.append(int(fname[0:3]) - 1)

        return imgs, classes, class_to_idx


class CUB200(data.Dataset):
    """`CUB200 <http://www.vision.caltech.edu/visipedia/CUB-200.html>`_ Dataset.
       `CUB200 <http://www.vision.caltech.edu/visipedia/CUB-200-2011.html>`_ Dataset.
    Args:
        root (string): Root directory of dataset the images and corresponding lists exist
            inside raw folder
        train (bool, optional): If True, creates dataset from ``training.pt``,
            otherwise from ``test.pt``.
        download (bool, optional): If true, downloads the dataset from the internet and
            puts it in root directory. If dataset is already downloaded, it is not
            downloaded again.
        transform (callable, optional): A function/transform that  takes in an PIL image
            and returns a transformed version. E.g, ``transforms.RandomCrop``
        target_transform (callable, optional): A function/transform that takes in the
            target and transforms it.
        year (int): Year/version of the dataset. Available options are 2010 and 2011
    """
    urls = []
    raw_folder = 'raw'

    def __init__(self, root, year, train=True, transform=None, target_transform=None, download=False,
                 loader=default_loader):
        self.root = os.path.expanduser(root)
        self.transform = transform
        self.target_transform = target_transform
        self.train = train
        self.year = year
        self.loader = loader

        assert year == 2010 or year == 2011, "Invalid version of CUB200 dataset"
        if year == 2010:
            self.urls = ['http://www.vision.caltech.edu/visipedia-data/CUB-200/images.tgz',
                         'http://www.vision.caltech.edu/visipedia-data/CUB-200/lists.tgz']

        elif year == 2011:
            self.urls = ['http://www.vision.caltech.edu/visipedia-data/CUB-200-2011/CUB_200_2011.tgz']

        if download:
            self.download()

        if not self._check_exists():
            raise RuntimeError('Dataset not found. You can use download=True to download it')

        #self.data_set = build_set(os.path.join(self.root, self.raw_folder), self.year, self.train)
        #pdb.set_trace()
        self.imgs, self.classes, self.class_to_idx = build_set(os.path.join(self.root, self.raw_folder),
                                                               self.year, self.train)

    def __getitem__(self, index):
        """
        Args:
            index (int): Index
        Returns:
            tuple: (image, target) where target is index of the target class.
        """
        path, target = self.imgs[index]
        img = self.loader(path)
        #print(img)
        if self.transform is not None:
            img = self.transform(img)

        if self.target_transform is not None:
            img = self.target_transform(img)
        #print(img.size())
        return img, target

    def _check_exists(self):
        pth = os.path.join(self.root, self.raw_folder)
        if self.year == 2010:
            return os.path.exists(os.path.join(pth, 'images/')) and os.path.exists(os.path.join(pth, 'lists/'))
        elif self.year == 2011:
            return os.path.exists(os.path.join(pth, 'CUB_200_2011/'))

    def __len__(self):
        return len(self.imgs)

    def download(self):
        from six.moves import urllib
        import tarfile

        if self._check_exists():
            return

        try:
            os.makedirs(os.path.join(self.root, self.raw_folder))
        except OSError as e:
            if e.errno == errno.EEXIST:
                pass
            else:
                raise

        for url in self.urls:
            print('Downloading ' + url)
            data = urllib.request.urlopen(url)
            filename = url.rpartition('/')[2]
            file_path = os.path.join(self.root, self.raw_folder, filename)
            with open(file_path, 'wb') as f:
                f.write(data.read())
            tar = tarfile.open(file_path, 'r')
            for item in tar:
                tar.extract(item, file_path.replace(filename, ''))
            os.unlink(file_path)

        print('Done!')