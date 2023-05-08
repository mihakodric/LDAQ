import os
import numpy as np
import time
import copy

from .daqtask import DAQTask
from .ni_task import NITaskOutput

class BaseGenerator:
    def __init__(self):
        self.is_running = True
        self.generation_name = "DefaultSignalGeneration"

    def generate(self):
        pass

    def run_generation(self):
        while self.is_running:
            self.generate()

    def set_data_source(self):
        pass

    def terminate_data_source(self):
        pass

    def stop(self):
        self.is_running = False
        self.terminate_data_source()


class NIGenerator(BaseGenerator):
    def __init__(self, task_name, signal, generation_name=None):
        super().__init__()
        self.task_name = task_name
        self.signal = signal

        self.NITask_used = False
        self.task_terminated = False

        if isinstance(task_name, str):
            self.task_name = task_name
            self.Task = DAQTask(self.task_name)
        elif isinstance(task_name, NITaskOutput):
            self.Task = task_name
            self.task_name = self.Task.task_name
            try:
                self.Task_base = copy.deepcopy(self.Task)
            except:
                raise Exception("NITaskOutput object must be defined again.")

            self.NITask_used = True
        else:
            raise TypeError("task_name has to be a string or NITaskOutput object.")
        
        self.generation_name = task_name if generation_name is None else generation_name

    def set_data_source(self):
        if self.task_terminated:
            if self.NITask_used:
                self.Task = copy.deepcopy(self.Task_base)
            else:
                self.Task = DAQTask(self.task_name)
            
            self.task_terminated = False
        
    def terminate_data_source(self):
        self.task_terminated = True
        self.clear_task()
    
    def generate(self):
        self.Task.generate(self.signal, clear_task=False)

    def clear_task(self):
        if hasattr(self, 'Task'):
            self.Task.clear_task(wait_until_done=False)

            # generate zeros
            self.Task = DAQTask(self.task_name)
            zero_signal = np.zeros((self.signal.shape[0], 10))
            self.Task.generate(zero_signal, clear_task=False)
            self.Task.clear_task(wait_until_done=False)
            
            del self.Task

    def run_generation(self):
        self.is_running = True
        
        self.set_data_source()
        time.sleep(0.1)

        if self.NITask_used:
            self.Task.initiate()

        self.generate()
        