import time
import datetime
import os
import numpy as np
import keyboard
from beautifultable import BeautifulTable

import threading
import pickle
import sys
import traceback
from .utils import load_measurement
        
class Core():
    def __init__(self, acquisitions, generations=None, controls=None, visualization=None):
        """
        Initializes the Core instance by initializing its acquisition, generation, control and visualization sources. 
        
        Args:
            acquisitions (list): list of acquisition sources. If None, initializes as empty list.
            generations (list): list of generation sources. If None, initializes as empty list.
            controls (list): list of control sources. If None, initializes as empty list.
            visualization: visualization source. If None, initializes as empty.

        """
        acquisitions = [] if acquisitions is None else acquisitions
        generations  = [] if generations is None else generations
        controls     = [] if controls is None else controls
        
        self.acquisitions  = acquisitions if isinstance(acquisitions,list ) else [acquisitions]
        self.generations   = generations  if isinstance(generations, list ) else [generations]
        self.controls      = controls     if isinstance(controls,    list ) else [controls]
        self.visualization = visualization
        
        self.acquisition_names = [acq.acquisition_name for acq in self.acquisitions]
        self.generation_names = [gen.generation_name for gen in self.generations]
        if any(self.acquisition_names.count(s) > 1 for s in set(self.acquisition_names)): # check for duplicate acq. names
            raise Exception("Two or more acquisition sources have the same name. Please make them unique.")
        if any(self.generation_names.count(s) > 1 for s in set(self.generation_names)):
            raise Exception("Two or more generation sources have the same name. Please make them unique.")
        for control in self.controls:
            control._retrieve_core_object(self) # give control object access to core object
        
        self.trigger_source_index = None
        
    def synchronize_acquisitions(self):
        """
        TODO: Currently no serious synchronization is done. This method is a placeholder for future synchronization.
        """
        pass
    
    def run(self, measurement_duration=None, autoclose=True, autostart=False, save_interval=None, run_name="Run", root='', verbose=2):
        """
        Runs the measurement with acquisition and generation sources that have already been set. This entails setting configuration
        and making acquiring and generation threads for each source, as well as starting and stopping them when needed. If visualization
        has been defined, it will run in a separate thread.
        
        Args:
            measurement_duration (float): measurement duration in seconds, from trigger event of any of the sources.
                                            If None, the measurement runs for the duration specified with set_trigger()
                                            method and the measurement_duration is None, measurement will take place for
                                            duration specified in set_trigger(). Default is None.
            autoclose (bool): whether the visualization should close automatically or not. Default is True.
            autostart (bool): whether the measurement should start automatically or not. If True, start as soon as all the
                              acquisition sources are ready. This is not recommended when measuring with different
                              acquisition sources, as the delay between the sources is generally increased.  Defaults to False. 
            save_interval (float): data is saved every 'save_periodically' seconds. Defaults to None, meaning data is not saved.
            run_name (str): name of the run. This name is used to save measurements when periodic saving is turned on. Default is "Run".
            root (str): root directory where measurements are saved. Default is empty string.
            verbose (int): 0 (print nothing), 1 (print status) or 2 (print status and hotkey legend). Default is 2.
            
        Returns:
            None   
        """
        if not hasattr(self, 'measurement_duration'):
            self.measurement_duration = measurement_duration
        elif measurement_duration is not None:
            self.measurement_duration = measurement_duration
            
        self.run_name = run_name
        self.verbose  = verbose
        self.save_interval = save_interval
        self.root = root
        self.autoclose = autoclose
        self.is_running_global = True
        self.autostart = autostart
        
        self.first = True # for printing trigger the first time.
        
        if self.visualization is None:
            self._keyboard_hotkeys_setup()
            if self.verbose == 2:
                self._print_table()
        else:
            self.verbose = 0
        
        if self.verbose in [1, 2]:
            print('\nWaiting for trigger...', end='')

        ####################
        # Thread setting:  #
        ####################
        
        self.lock = threading.Lock() # for locking a thread if needed.    
        self.stop_event = threading.Event()
        self.triggered_globally = False
        self.thread_list = []

        # Make separate threads for data acquisition
        for acquisition in self.acquisitions:
            # update triggers from acquisition to match acquired samples to run_time:
            acquisition.is_standalone = False
            acquisition.reset_trigger()
            if self.measurement_duration is not None:
                acquisition.update_trigger_parameters(duration=self.measurement_duration, duration_unit="seconds")
            if self.save_interval is not None:
                # update ringbuffer sizes to 1.2x the save size:
                acquisition.set_continuous_mode(True, measurement_duration=self.measurement_duration)
                acquisition.update_trigger_parameters(duration=1.2*self.save_interval, duration_unit="seconds")
            else:
                acquisition.set_continuous_mode(False)
                
            if autostart:
                acquisition.update_trigger_parameters(level=1e40)   
                
            thread_acquisition = threading.Thread(target= self._stop_event_handling(acquisition.run_acquisition)  )
            self.thread_list.append(thread_acquisition)

        # If generation is present, create generation thread
        for generation in self.generations:
            thread_generation  = threading.Thread(target= self._stop_event_handling(generation.run_generation) )
            self.thread_list.append(thread_generation)

        # If control is present, create control thread
        for control in self.controls:
            thread_control = threading.Thread(target= self._stop_event_handling(control.run_control) )
            self.thread_list.append(thread_control)
             
        # check events that can stop the acquisition:
        thread_check_events = threading.Thread(target= self._stop_event_handling( self._check_events) )
        self.thread_list.append(thread_check_events)
        
        # periodic data saving:
        if self.save_interval is not None:
            # create saving thread
            thread_periodic_saving = threading.Thread(target= self._stop_event_handling(self._save_measurement_periodically) )
            self.thread_list.append(thread_periodic_saving)
            
        # start all threads:
        for thread in self.thread_list:
            thread.start()
        time.sleep(0.2)

        # TODO: using self.stop_event.is_set() terminate threads if one thread fails.
        #       self.stop_event.set() is called in _stop_event_handling() wrapper function
        if self.visualization is not None:
            self._stop_event_handling( self.visualization.run )(self)
        else:
            # Main Loop if no visualization:
            while self.is_running_global:
                time.sleep(0.5)

        # on exit:
        self.stop_acquisition_and_generation()
        
        for thread in self.thread_list:
            thread.join()
            
        if self.verbose in [1, 2]:
            print('Measurement finished.')
        
        if self.visualization is None:
            self._keyboard_hotkeys_remove()
    
    def _stop_event_handling(self, func):
        """Used to handle Exception events in a process.

        Args:
            func (func): Function that will be run in thread.
        """
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception:
                print("An exception occurred in a process:")
                traceback.print_exception(*sys.exc_info())
                self.stop_event.set()
                
        return wrapper
    
    def _check_events(self):
        """
        Checks for different events required to perform measurements. 
        It checks whether all acquisition and generation sources are running or not; if any of them are not running, 
        then it terminates the measurement. It also checks if any acquisition sources are triggered or if any additional 
        check functions added with add_check_events() method return True. If either of these conditions returns True, 
        it terminates the measurement. This function runs continuously in a separate thread until the is_running_global 
        variable is set to False.

        Args:
            None
            
        Returns:
            None
        """
        while self.is_running_global:
            acquisition_running = True
            if all(not acquisition.is_running for acquisition in self.acquisitions) and len(self.acquisitions) > 0:
                acquisition_running = False # end if all acquisitions are ended
            
            generation_running = True
            if all(not generation.is_running for generation in self.generations) and len(self.generations) > 0:
                generation_running = False
                
            control_running = True
            if all(not control.is_running for control in self.controls) and len(self.controls) > 0:
                control_running = False
                
            self.is_running_global = acquisition_running and generation_running and control_running
            
            # check that all acquisitions are ready:
            if not self.acquisitions[0].all_acquisitions_ready:
                all_acquisitions_ready = all(acq.is_ready for acq in self.acquisitions)
                if all_acquisitions_ready:
                    self.acquisitions[0]._all_acquisitions_ready()
                    if self.autostart:
                        self.start_acquisition()
            
            if any(acq.is_triggered() for acq in self.acquisitions) and not self.triggered_globally:
                self.triggered_globally = True
                
            if self.first and self.triggered_globally:
                if self.verbose in [1, 2]:
                    print()
                    print('triggered.') 
                    print('\tRecording...', end='') 
                self.first = False
                            
            # additional functionalities added with 'add_check_events()' method:   
            if hasattr(self, "additional_check_functions"):
                for fun in self.additional_check_functions:
                    if fun(self):
                        self.stop_acquisition_and_generation()
                                                
            time.sleep(0.05)   
            
    def add_check_events(self, *args):
        """
        Takes functions as input arguments that take only "self" argument and returns True/False. If any of the provided functions
        is True, the acquisition will be stopped. This can be used to add additional functionalities to the measurement, such as
        stopping the measurement if a certain condition is met.
        
        Each time this function is called, the previous additional check functions are erased. 
        
        Example:
            >>> def check_temperature(self):
            >>>     acq = self.acquisitions[0] # take 1st acquisition source
            >>>     temperature = acq.get_measurement_dict()['data'][:, 0] # take 1st channel
            >>>     # stop the measurement if temperature is above 50 degrees:
            >>>     if temperature > 50:
            >>>         return True
            >>>     else:
            >>>         return False
        """
        self.additional_check_functions = []
        for fun in args:
            self.additional_check_functions.append(fun)   
                
    def set_trigger(self, source, channel, level, duration, duration_unit='seconds', presamples=0, trigger_type='abs'):
        """    
        Set parameters for triggering the measurement. 
    
        Args:
            source (int, str): Index (position in the 'self.acquisitions' list) or name of the acquisition source as a 
                                        string ('acquisition.acquisition_name') for which trigger is to be set. 
            channel (int, str): trigger channel (int or str). If str, it must be one of the channel names. If int, 
                                index from self.channel_names ('data' channels) has to be provided (NOTE: see the difference between
                                self.channel_names and self.channel_names_all).
            level (float): trigger level
            duration (float, int, optional): duration of the acquisition after trigger (in seconds or samples). Defaults to 1.
            duration_unit (str, optional): 'seconds' or 'samples'. Defaults to 'seconds'.
            presamples (int, optional): number of presamples to save. Defaults to 0.
            type (str, optional): trigger type: up, down or abs. Defaults to 'abs'.
            
        Returns:
            None

        NOTE: only one trigger channel is supported at the moment. Additionally trigger can only be set
        on 'data' channels. If trigger is needed on 'video' channels, a 'data' virtual channel has to be created
        using 'add_virtual_channel()' method, and then trigger can be set on this virtual channel.
        """
        duration_unit = duration_unit.lower()
        trigger_type  = trigger_type.lower()
        
        if duration_unit=="samples":
            duration = int(duration)
            
        # set external trigger option to all acquisition sources:
        if type(source) == str:
            source = self.acquisition_names.index(source)
        self.trigger_source_index = source # save source index on which trigger is set
        
        for idx, acq in enumerate(self.acquisitions):
            if idx == source: #set trigger
                acq.set_trigger(
                    level=level, 
                    channel=channel, 
                    duration=duration, 
                    duration_unit=duration_unit, 
                    presamples=presamples, 
                    type=trigger_type
                )
            else:
                source_sample_rate = self.acquisitions[source].sample_rate
                presamples_seconds = presamples/source_sample_rate
                presamples_other   = int(presamples_seconds*acq.sample_rate)
                
                if duration_unit == "seconds":
                    duration_seconds = duration
                    acq.update_trigger_parameters(duration=duration_seconds, duration_unit="seconds", presamples=presamples_other)
                elif duration_unit == "samples": # if specified as samples convert to seconds for other acquisition sources.
                    duration_seconds = duration/source_sample_rate
                    duration_samples = int(duration_seconds*acq.sample_rate)
                    acq.update_trigger_parameters(duration=duration_samples, duration_unit="samples", presamples=presamples_other)
                    
                else:
                   raise KeyError("Invalid duration unit specified. Only 'seconds' and 'samples' are possible.")
            
            if duration_unit == "seconds":
                self.measurement_duration = duration
            elif duration_unit == "samples":
                self.measurement_duration = duration/source_sample_rate
            else:
                pass # should not happen
            
    def _keyboard_hotkeys_setup(self):
        """Adds keyboard hotkeys for interaction.
        """
        id1 = keyboard.add_hotkey('s', self.start_acquisition)
        id2 = keyboard.add_hotkey('q', self.stop_acquisition_and_generation)
        self.hotkey_ids = [id1, id2]
        
    def _keyboard_hotkeys_remove(self):
        """Removes all keyboard hotkeys defined by 'keyboard_hotkeys_setup'.
        """
        for id in self.hotkey_ids:
            keyboard.remove_hotkey(id)
            
    def stop_acquisition_and_generation(self):
        """Stops all acquisition and generation sources.
        """
        for acquisition in self.acquisitions:
            try:
                acquisition.stop()
            except:
                pass
        for generation in self.generations:
            try:
                generation.stop()
            except:
                pass
            
    def start_acquisition(self):
        """Starts acquisitions sources.
        """
        if not self.triggered_globally:
            self.triggered_globally = True
            
            # 1 acq source triggers others through CustomPyTrigger parent class
            with self.acquisitions[0].lock_acquisition: 
                self.acquisitions[0].activate_trigger()
    
    def _print_table(self):
        """Prints the table of the hotkeys of the application to the console.
        The table contains the hotkeys, as well as a short description of each
        hotkey. The table is printed using the BeautifulTable library.
        """
        table = BeautifulTable()
        table.rows.append(["s", "Start the measurement manually (ignore trigger)"])
        table.rows.append(["q", "Stop the measurement"])
        table.columns.header = ["HOTKEY", "DESCRIPTION"]
        print(table)
     
    def _get_measurement_dict_PLOT(self):
        """
        Returns only NEW acquired data from all sources.
        
        NOTE: This function is used for plotting purposes only.
        'get_measurement_dict(N_seconds="new")' should be used instead.
        """
        new_data_dict = {}
        for idx, acq in enumerate(self.acquisitions):
            # retireves new data from this source
            new_data_dict[self.acquisition_names[idx]] = acq.get_data_PLOT() 
        return new_data_dict
    
    def get_measurement_dict(self, N_seconds=None):
        """Returns measured data from all sources.

        Args:
            N_seconds (float, str, optional): last number of seconds of the measurement. 
                        if "new" then only new data is returned. Defaults to None. When 
                        Core() class is run with run() method and periodic saving, N_seconds="new"
                        should not be used as it will cause data loss.

        Returns:
            dict: Measurement dictionary. 1st level keys are acquisition names and its values are acquisitions dictionaries.
                  Those have the following structure:
                  {'time': 1D array, 
                    'channel_names': self.channel_names, 'data': 2D array (n_samples, n_data_channels),
                    'channel_names_video': self.channel_names_video, 'video': list of 3D arrays (n_samples, height, width),
                    'sample_rate': self.sample_rate}
        """        
        self.measurement_dict = {}
        for idx, name in enumerate(self.acquisition_names):
            if N_seconds is None:
                N_points = None
            elif type(N_seconds)==float or type(N_seconds)==int:
                N_points = int( N_seconds * self.acquisitions[idx].sample_rate ) 
            elif N_seconds=="new":
                N_points = N_seconds # "new" is stored in N_points to be passed to get_data() method
            else:
                raise KeyError("Wrong argument type passed to N_seconds.")
                
            self.measurement_dict[ name ] = self.acquisitions[idx].get_measurement_dict(N_points)
        
        return self.measurement_dict    
    
    def save_measurement(self, name=None, root=None, timestamp=True, comment=None):
        """Save acquired data from all sources into one dictionary saved as pickle. See get_measurement_dict() method for the 
           structure of the dictionary.
        
        Args:
            name (str, optional): filename, if None filename defaults to run name specified in run() method. Defaults to None.
            root (str, optional): directory to save to. Defaults to None.
            timestamp (bool, optional): include timestamp before 'filename'. Defaults to True.
            comment (str, optional): comment on the saved file. Defaults to None.
            
        Returns:
            str: path to the saved file
        """
        if name is None:
            name = self.run_name
        if root is None:
            root = self.root
            
        self.measurement_dict = self.get_measurement_dict()
        if comment is not None:
            self.measurement_dict['comment'] = comment
            
        if not os.path.exists(root) and root != '':
            os.mkdir(root)

        if timestamp:
            now = datetime.datetime.now()
            stamp = f'{now.strftime("%Y%m%d_%H%M%S")}_'
        else:
            stamp = ''

        filename = f'{stamp}{name}.pkl'
        path = os.path.join(root, filename)
        with open(path, 'wb') as f:
            pickle.dump(self.measurement_dict, f, protocol=-1)

        return path  
     
    def _save_measurement_periodically(self):
        """Periodically saves the measurement data."""
        name = self.run_name
        root = self.root

        start_time = time.time()
        file_index = 0
        file_created = False

        running = True
        delay_saving = 0.5  # seconds
        delay_start = time.time()

        while running:
            time.sleep(0.2)

            # implemented time delay:
            if self.is_running_global:
                delay_start = time.time()
            elif time.time() - delay_start > delay_saving:
                running = False
            else:
                pass

            # periodic saving:
            if self.triggered_globally:
                elapsed_time = time.time() - start_time
                if elapsed_time >= self.save_interval:
                    start_time = time.time()

                    if not file_created:
                        now = datetime.datetime.now()
                        file_name = f"{now.strftime('%Y%m%d_%H%M%S')}_{name}.pkl"
                        file_created = True

                    file_index = self._open_and_save(file_name, root, file_index)

        if self.triggered_globally:
            time.sleep(0.5)
            self._open_and_save(file_name, root, file_index)

    def _open_and_save(self, file_name_base, root, file_index):
        """
        Open existing file and save new data.
        
        Args:
            file_name_base (str): file name without index and extension
            root (str): directory to save to
            file_index (int): index of the file
            
        Returns:
            int: updated file index
        """
        max_file_size = 200 * 1024 * 1024  # 200 MB - maximum file size

        file_name_base, ext = os.path.splitext(file_name_base)
        file_index_str = str(file_index).zfill(4)
        file_name = f"{file_name_base}_{file_index_str}{ext}"
        file_path = os.path.join(root, file_name)

        # Load existing data
        if os.path.exists(file_path):
            current_file_size = os.path.getsize(file_path)
        else:
            current_file_size = 0

        # Check if file size exceeds 100 MB, create a new file with incremented index
        if current_file_size >= max_file_size:
            file_index += 1 # update file index
            
            # get previous times for each acquisition:
            data = load_measurement(file_name, root)
            time_last_dict = {acq.acquisition_name: data[acq.acquisition_name]["time"][-1] for acq in self.acquisitions}
        else:
            time_last_dict = {acq.acquisition_name: 0 for acq in self.acquisitions}
            
        file_name = f"{file_name_base}_{file_index}{ext}"
        file_path = os.path.join(root, file_name)
        
        if os.path.exists(file_path):
            data = load_measurement(file_name, root)
        else:
            data = {}

        # Update data with new measurements
        for acq in self.acquisitions:
            name = acq.acquisition_name
            if acq.is_triggered():
                measurement = acq.get_measurement_dict(N_points="new")

                if name not in data:
                    data[name] = measurement
                    data[name]['time'] += time_last_dict[name] + 1 / acq.sample_rate
        
                else:
                    if len(data[name]['time']) > 0:
                        time_last = data[name]['time'][-1]
                    else:
                        time_last = time_last_dict[name]
                        
                    new_time = measurement['time'] + time_last + 1 / acq.sample_rate
                    data[name]['time'] = np.concatenate((data[name]['time'], new_time), axis=0)
                    
                    if 'data' in measurement.keys():
                        new_data = measurement['data']
                        data[name]['data'] = np.concatenate((data[name]['data'], new_data), axis=0)
                    if 'video' in measurement.keys():
                        new_video = measurement['video']
                        data[name]['video'] = [np.concatenate((data[name]['video'][i], new_video[i]), axis=0) for i in range(len(new_video))]
                    

        # Save updated data
        with open(file_path, 'wb') as f:
            pickle.dump(data, f, protocol=-1)

        return file_index
