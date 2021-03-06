import os
import numpy as np
import matplotlib.pyplot as plt
from tqdm import trange, tqdm
from torch.utils.data import DataLoader
from torchvision.datasets import MNIST
import torchvision.transforms as transforms
from math import log, exp, floor

from model import Model
from evolution import generate_graph, visualize_structure


def build_data_loader(is_train, batch_size):
    download = not os.path.exists('data/MNIST')
    transform = transforms.Compose([transforms.ToTensor(),
                                    transforms.Normalize((0.1307,), (0.3081,))
                                  ])
    dataset = MNIST(root='data', train=is_train,
                    transform=transform, download=download)
    return DataLoader(dataset, batch_size=batch_size, shuffle=True)


class Graph(object):
  def __init__(self, n, type, flag, train_batch_size=60, eval_batch_size=60):
    # models
    self.n = n
    self.c = 0.3
    self.models = [Model(id) for id in range(n)]
    self.retired_models = []
    self.n_parents = floor(n / 2.)
    self.type = type
    self.flag = flag
    # graph
    (self.adjMat,
     self.childrenList) = generate_graph(n, type=type, flag=flag)
    # data loading
    self.train_loader = build_data_loader(True, train_batch_size)
    self.eval_loader = build_data_loader(True, eval_batch_size)
    # global param tracking
    self.global_params = {'fitness': [], 'mean_lr': []}

  def get_normed_fitness(self, x_batch, y_batch, track=False):
    fitnesses = np.array([(1 / min(10000, model.eval(x_batch, y_batch)))
                          for model in self.models])
    if track:
        self.global_params['fitness'].append(np.mean(fitnesses))
    return (fitnesses / self.n)

  def step_models(self, x_batch, y_batch):
    for model in self.models:
      model.step(x_batch, y_batch)
    return True

  def select_parents(self, fitnesses):
      inv_fitnesses = [fit for fit in fitnesses]
      fitSum = sum(inv_fitnesses)
      p = [fit/fitSum for fit in inv_fitnesses]
      return np.random.choice(range(self.n), size=self.n_parents, p=p)

  def select_child(self, parent):
    p = self.adjMat[parent]
    if sum(p) > 0:
      child = np.random.choice(range(self.n), p=p)
    else:
      child = None
    return child

  def get_new_param(self, parent_param, child_param):
    delta_param = (parent_param - child_param)
    if delta_param > 0:
        delta_param = 1
    elif delta_param < 0:
        delta_param = -1
    delta_param *= self.c
    log_child_param = log(child_param) - log(1 - child_param)
    log_child_param += np.tanh(delta_param)
    child_param = 1.0 / (1 + exp(-log_child_param))
    return child_param

  def update_models(self, x_eval_batch, y_eval_batch):
    fitnesses = self.get_normed_fitness(x_eval_batch, y_eval_batch, track=True)
    parents = self.select_parents(fitnesses)
    for parent in parents:
        child = self.select_child(parent)
        child_model = self.models[child]
        parent_param = self.models[parent].fetch_lr()
        child_param = child_model.fetch_lr()
        child_param = self.get_new_param(parent_param, child_param)
        child_model.update_hyperparams(child_param)
    for model in self.models:
        model.log_hyperparams()
    return fitnesses

  def list_model_lrs(self):
      return [model.param_logs['lr'][-1] for model in self.models]

  def log_global_params(self):
    lr_buffer = self.list_model_lrs()
    self.global_params['mean_lr'].append(np.mean(lr_buffer))
    return True

  def train(self, steps=None, schedule=None):
    if schedule is None:
        for step in trange(steps, desc='Training'):
          x_train_batch, y_train_batch = next(iter(self.train_loader))
          self.step_models(x_train_batch, y_train_batch)
          x_eval_batch, y_eval_batch = next(iter(self.eval_loader))
          self.update_models(x_eval_batch, y_eval_batch)
          self.log_global_params()
    else:
        assert steps is None, 'Cannot train with both schedule and steps.'
        for item, plan in enumerate(schedule):
            steps = plan[0]
            target_n = plan[1]
            target_flag = plan[2]
            n_diff = self.n - target_n
            if target_flag != self.flag:
                self.flag = target_flag
                (self.adjMat,
                 self.childrenList) = generate_graph(self.n,self.type,self.flag)
            lrs = self.list_model_lrs()
            visualize_structure(item, lrs, self.childrenList,
                                type=self.type,flag=self.flag)
            for step in trange(steps, desc="ScheduledTraining"):
                x_train_batch, y_train_batch = next(iter(self.train_loader))
                self.step_models(x_train_batch, y_train_batch)
                x_eval_batch, y_eval_batch = next(iter(self.eval_loader))
                fitnesses = self.update_models(x_eval_batch, y_eval_batch)
                self.log_global_params()

                # at a time step remove the least fit
                if (n_diff > 0):
                    if (step%(steps//n_diff)==(steps//(n_diff))-1):
                        val, idx = min((val, idx) for (idx, val)
                                       in enumerate(fitnesses))
                        self.retired_models.append(self.models.pop(idx))
                        self.n -= 1
                (self.adjMat,
                 self.childrenList) = generate_graph(self.n,self.type,self.flag)

    return True

  def vis_global_params(self, root=None, exclude=[]):
      ''' Plots all globally-tracked params '''
      if not os.path.exists(root):
          os.mkdir(root)
      for name, buffer in self.global_params.items():
          if name in exclude:
              continue
          plt.plot(buffer, label=name)
      plt.title(f'Global Params')
      plt.xlabel('Iteration')
      plt.legend()
      if not root:
          plt.show()
      else:
          plt.savefig(f'{root}/global_params')
          plt.close()

  def vis_individual_params(self, root=None):
      ''' Plots graphs of each param across nets '''
      if not os.path.exists(root):
          os.mkdir(root)
      for name, buffer in self.models[0].param_logs.items():
          for model in (self.models + self.retired_models):
              plt.plot(model.param_logs[name], label=str(model))
          if 'lr' in name:
              plt.yscale('log')
          plt.xlabel('Iteration')
          plt.ylabel(name)
          plt.title(f'{name} Across Networks')
          if not root:
              plt.show()
          else:
              plt.savefig(f'{root}/indiv_params_{name}')
              plt.close()

  def vis_all_single_net(self, id, root=None, exclude=[]):
      ''' Plots all params of net with id=id on single graph '''
      if not os.path.exists(root):
          os.mkdir(root)
      model = self.models[id]
      for name, buffer in model.param_logs.items():
          if name in exclude:
              continue
          plt.plot(buffer, label=name)
      plt.title(f'Params for {model}')
      plt.legend()
      plt.xlabel('Iteration')
      if not root:
          plt.show()
      else:
          plt.savefig(f'{root}/model_params_{model}')
          plt.close()
