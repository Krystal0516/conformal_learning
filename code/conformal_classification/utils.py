import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
import torchvision
import torchvision.transforms as transforms
import time
import pathlib
import os
import pickle
from tqdm import tqdm
import pdb

def sort_sum(scores):
    I = scores.argsort(axis=1)[:,::-1]
    ordered = np.sort(scores,axis=1)[:,::-1]
    cumsum = np.cumsum(ordered,axis=1) 
    return I, ordered, cumsum

class AverageMeter(object):
    """Computes and stores the average and current value"""

    def __init__(self, name, fmt=':f'):
        self.name = name
        self.fmt = fmt
        self.reset()

    def reset(self):
        self.val = 0
        self.avg = 0
        self.sum = 0
        self.count = 0

    def update(self, val, n=1):
        self.val = val
        self.sum += val * n
        self.count += n
        self.avg = self.sum / self.count

    def __str__(self):
        fmtstr = '{name} {val' + self.fmt + '} ({avg' + self.fmt + '})'
        return fmtstr.format(**self.__dict__)

def validate(val_loader, model, print_bool):
    coverage = AverageMeter('Coverage')
    size = AverageMeter('Size')
    model.eval()
    
    with torch.no_grad():
        for x, target in val_loader:
            x = x.cuda()
            target = target.cuda()
            _, S = model(x)
            
            # 转换target为多标签索引格式
            target_indices = [torch.where(t == 1)[0].tolist() for t in target]
            
            batch_coverage = 0
            batch_size_count = 0
            for i in range(len(S)):
                true_labels = target_indices[i]
                pred_labels = S[i]
                if all(label in pred_labels for label in true_labels):
                    batch_coverage += 1
                batch_size_count += len(pred_labels)
            
            coverage.update(batch_coverage/x.size(0), x.size(0))
            size.update(batch_size_count/x.size(0), x.size(0))
    
    return coverage.avg, size.avg

def coverage_size(S,targets):
    covered = 0
    size = 0
    for i in range(targets.shape[0]):
        if (targets[i].item() in S[i]):
            covered += 1
        size = size + S[i].shape[0]
    return float(covered)/targets.shape[0], size/targets.shape[0]

def accuracy(output, target, topk=(1,)):
    """Computes the precision@k for the specified values of k"""
    maxk = max(topk)
    batch_size = target.size(0)

    _, pred = output.topk(maxk, 1, True, True)
    pred = pred.t()
    correct = pred.eq(target.view(1, -1).expand_as(pred))

    res = []
    for k in topk:
        correct_k = correct[:k].float().sum()
        res.append(correct_k.mul_(100.0 / batch_size))
    return res

def data2tensor(data):
    imgs = torch.cat([x[0].unsqueeze(0) for x in data], dim=0).cuda()
    targets = torch.cat([torch.Tensor([int(x[1])]) for x in data], dim=0).long()
    return imgs, targets

def split2ImageFolder(path, transform, n1, n2):
    dataset = torchvision.datasets.ImageFolder(path, transform)
    data1, data2 = torch.utils.data.random_split(dataset, [n1, len(dataset)-n1])
    data2, _ = torch.utils.data.random_split(data2, [n2, len(dataset)-n1-n2])
    return data1, data2

def split2(dataset, n1, n2):
    data1, temp = torch.utils.data.random_split(dataset, [n1, dataset.tensors[0].shape[0]-n1])
    data2, _ = torch.utils.data.random_split(temp, [n2, dataset.tensors[0].shape[0]-n1-n2])
    return data1, data2

def get_model(modelname):
    if modelname == 'ResNet18':
        model = torchvision.models.resnet18(pretrained=True, progress=True)

    elif modelname == 'ResNet50':
        model = torchvision.models.resnet50(pretrained=True, progress=True)

    elif modelname == 'ResNet101':
        model = torchvision.models.resnet101(pretrained=True, progress=True)

    elif modelname == 'ResNet152':
        model = torchvision.models.resnet152(pretrained=True, progress=True)

    elif modelname == 'ResNeXt101':
        model = torchvision.models.resnext101_32x8d(pretrained=True, progress=True)

    elif modelname == 'VGG16':
        model = torchvision.models.vgg16(pretrained=True, progress=True)

    elif modelname == 'ShuffleNet':
        model = torchvision.models.shufflenet_v2_x1_0(pretrained=True, progress=True)

    elif modelname == 'Inception':
        model = torchvision.models.inception_v3(pretrained=True, progress=True)

    elif modelname == 'DenseNet161':
        model = torchvision.models.densenet161(pretrained=True, progress=True)

    else:
        raise NotImplementedError

    model.eval()
    model = torch.nn.DataParallel(model).cuda()

    return model

# Computes logits and targets from a model and loader
def get_logits_targets(model, loader):
    logits = torch.zeros((len(loader.dataset), 1000)) # 1000 classes in Imagenet.
    labels = torch.zeros((len(loader.dataset),))
    i = 0
    print(f'Computing logits for model (only happens once).')
    with torch.no_grad():
        for x, targets in tqdm(loader):
            batch_logits = model(x.cuda()).detach().cpu()
            logits[i:(i+x.shape[0]), :] = batch_logits
            labels[i:(i+x.shape[0])] = targets.cpu()
            i = i + x.shape[0]
    
    # Construct the dataset
    dataset_logits = torch.utils.data.TensorDataset(logits, labels.long()) 
    return dataset_logits

def get_logits_dataset(modelname, datasetname, datasetpath, cache=str(pathlib.Path(__file__).parent.absolute()) + '/experiments/.cache/'):
    fname = cache + datasetname + '/' + modelname + '.pkl' 

    # If the file exists, load and return it.
    if os.path.exists(fname):
        with open(fname, 'rb') as handle:
            return pickle.load(handle)

    # Else we will load our model, run it on the dataset, and save/return the output.
    model = get_model(modelname)

    transform = transforms.Compose([
                    transforms.Resize(256),
                    transforms.CenterCrop(224),
                    transforms.ToTensor(),
                    transforms.Normalize(mean=[0.485, 0.456, 0.406],
                                         std =[0.229, 0.224, 0.225])
                    ])
    
    dataset = torchvision.datasets.ImageFolder(datasetpath, transform)
    loader = torch.utils.data.DataLoader(dataset, batch_size = 32, shuffle=False, pin_memory=True)

    # Get the logits and targets
    dataset_logits = get_logits_targets(model, loader)

    # Save the dataset 
    os.makedirs(os.path.dirname(fname), exist_ok=True)
    with open(fname, 'wb') as handle:
        pickle.dump(dataset_logits, handle, protocol=pickle.HIGHEST_PROTOCOL)

    return dataset_logits
