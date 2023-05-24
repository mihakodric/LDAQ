import pyqtgraph as pg
from pyqtgraph import ImageView, ImageItem
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QGridLayout, QVBoxLayout, QPushButton, QHBoxLayout, QDesktopWidget, QProgressBar, QLabel
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QColor, QPainter, QBrush, QPen, QIcon

import numpy as np
import sys
import os
import random
import time
import types
import keyboard
from pyTrigger import RingBuffer2D

from .visualization_helpers import compute_nth, check_subplot_options_validity, _fun_fft, _fun_frf_amp, _fun_frf_phase, _fun_coh

INBUILT_FUNCTIONS = {'fft': _fun_fft, 'frf_amp': _fun_frf_amp, 'frf_phase': _fun_frf_phase, 'coh': _fun_coh}
    
    
class Visualization:
    def __init__(self, refresh_rate=100, max_points_to_refresh=1e4, sequential_plot_updates=True):
        """Live visualization of the measured data.

        For more details, see [documentation](https://ladiskdaq.readthedocs.io/en/latest/visualization.html).
        
        :param refresh_rate: Refresh rate of the plot in ms.
        :param max_points_to_refresh: Maximum number of points to refresh in the plot. Adjust this number to optimize performance.
            This number is used to compute the ``nth`` value automatically.
        :param sequential_plot_updates: If ``True``, the plot is updated sequentially (one in each iteration of the main loop).
            If ``False``, all lines are updated in each iteration of the main loop.

        .. note::

            If ``sequential_plot_updates`` is ``True``, the lines are updated sequentially in each iteration of the main loop.
            Potentially, the plot can show a phase shift between the lines. This is because when the first line is updated,
            the data for the second line is already acquired. To avoid this, set ``sequential_plot_updates`` to ``False``.
        """
        self.max_plot_time = 1
        self.show_legend = True
        self.refresh_rate = refresh_rate
        self.plots = None
        self.subplot_options = {}
        self.add_line_widget = False
        self.add_image_widget = False
        
        self.update_refresh_rate = 10 # [ms] interval of calling the plot_update function
        self.max_points_to_refresh = max_points_to_refresh
        self.sequential_plot_updates = sequential_plot_updates
    

    def add_lines(self, position, source, channels, function=None, nth="auto", refresh_rate=None):
        """Build the layout dictionary.

        :param position: tuple, the position of the subplot. Example: ``(0, 0)``.
        :param source: string, the source of the data. Name that was given to the ``Acquisition`` object.
        :param channels: list of integers, the channels from the ``source`` to be plotted. Can also be a list of tuples
            of integers to plot channel vs. channel. Example: ``[(0, 1), (2, 3)]``.
        :param function: function, the function to be applied to the data before plotting. If ``channels`` is a list of tuples,
            the function is applied to each tuple separately.
        :param nth: int, the nth sample to be plotted. If ``nth`` is ``"auto"``, the nth sample is computed automatically.
        :param refresh_rate: int, the refresh rate of the subplot in milliseconds. If this argument is not specified, the
            refresh rate defined in the :class:`Visualization` is used.

        Channels
        ~~~~~~~~

        If the ``channels`` argument is an integer, the data from the channel with the specified index will be plotted.

        If the ``channels`` argument is a list of integers, the data from the channels with the specified indices will be plotted:

        >>> vis.add_lines(position=(0, 0), source='DataSource', channels=[0, 1])

        To plot channel vs. channel the ``channels`` argument is a tuple of two integers:

        >>> vis.add_lines(position=(0, 0), source='DataSource', channels=(0, 1))

        The first integer is the index of the x-axis and the second integer is the index of the y-axis.

        Multiple channel vs. channel plots can be added to the same subplot:

        >>> vis.add_lines(position=(0, 0), source='DataSource', channels=[(0, 1), (2, 3)])

        The ``function`` argument
        ~~~~~~~~~~~~~~~~~~~~~~~~

        The data can be processed on-the-fly by a specified function.


        The ``function`` can be specified by the user. To use the built-in functions, a string is passed to the ``function`` argument. 
        An example of a built-in function is "fft" which computes the [Fast Fourier Transform](https://numpy.org/doc/stable/reference/generated/numpy.fft.rfft.html)
        of the data with indices 0 and 1:

        >>> vis.add_lines(position=(0, 0), source='DataSource', channels=[0, 1], function='fft')

        To build a custom function, the function must be defined as follows:

        >>> def function(self, channel_data):
                '''
                :param self: instance of the acquisition object (has to be there so the function is called properly)
                :param channel_data: channel data
                '''
                return channel_data**2

        The ``self`` argument in the custom function referes to the instance of the acquisition object. 
        This connection can be used to access the properties of the acquisition object, e.g. sample rate.
        The ``channel_data`` argument is a list of numpy arrays, where each array corresponds to the data from one channel. 
        The data is acquired in the order specified in the ``channels`` argument.

        For the example above, the custom function is called for each channel separetely, the ``channel_data`` is a one-dimensional numpy array. 
        To add mutiple channels to the ``channel_data`` argument, the ``channels`` argument is modified as follows:

        >>> vis.add_lines(position=(0, 0), source='DataSource', channels=[(0, 1)], function=function)

        The ``function`` is now passed the ``channel_data`` with shape ``(N, 2)`` where ``N`` is the number of samples.
        The function can also return a 2D numpy array with shape ``(N, 2)`` where the first column is the x-axis and the second column is the y-axis.
        An example of such a function is:

        >>> def function(self, channel_data):
                '''
                :param self: instance of the acquisition object (has to be there so the function is called properly)
                :param channel_data: 2D channel data array of size (N, 2)
                :return: 2D array np.array([x, y]).T that will be plotted on the subplot.
                '''
                ch0, ch1 = channel_data.T
                x =  np.arange(len(ch1)) / self.acquisition.sample_rate # time array
                y = ch1**2 + ch0 - 10
                return np.array([x, y]).T

        """
        self.add_line_widget = True

        if not isinstance(source, str):
            raise ValueError("The source must be a string.")
        if not isinstance(position, tuple):
            raise ValueError("The position must be a tuple.")
        if not (isinstance(channels, list) or isinstance(channels, tuple) or isinstance(channels, int)):
            raise ValueError("The channels must be a list, tuple or an integer.")
        if not (isinstance(function, types.FunctionType) or function in INBUILT_FUNCTIONS.keys() or function is None):
            raise ValueError("The function must be a function or a string.")
        if not (isinstance(nth, int) or nth == 'auto'):
            raise ValueError("The nth must be an integer or 'auto'.")

        if self.plots is None:
            self.plots = {}
        
        if source not in self.plots.keys():
            self.plots[source] = []

        if isinstance(channels, int) or isinstance(channels, tuple):
            channels = [channels]

        if isinstance(function, types.FunctionType):
            apply_function = function
        elif function in INBUILT_FUNCTIONS.keys():
            apply_function = INBUILT_FUNCTIONS[function]
        else:
            apply_function = lambda x, y: y

        if refresh_rate:
            plot_refresh_rate = self.update_refresh_rate*(refresh_rate//self.update_refresh_rate)
        else:
            plot_refresh_rate = self.update_refresh_rate*(self.refresh_rate//self.update_refresh_rate)
        
        for channel in channels:
            self.plots[source].append({
                'pos': position,
                'channels': channel,
                'apply_function': apply_function,
                'nth': nth,
                'since_refresh': 1e40,
                'refresh_rate': plot_refresh_rate,
            })


    def add_image(self, source, function=None, refresh_rate=100, colormap='CET-L17'):
        """"""
        self.add_image_widget = True

        if self.plots is None:
            self.plots = {}
        
        if source not in self.plots.keys():
            self.plots[source] = []

        if isinstance(function, types.FunctionType):
            apply_function = function
        elif function in INBUILT_FUNCTIONS.keys():
            apply_function = INBUILT_FUNCTIONS[function]
        else:
            apply_function = lambda x, y: y
        

        self.plots[source].append({
            'pos': 'image',
            'channels': 'image',
            'apply_function': apply_function,
            'nth': 1,
            'since_refresh': 1e40,
            'refresh_rate': refresh_rate,
        })

        self.color_map = colormap


    def config_subplot(self, position, xlim=None, ylim=None, t_span=None, axis_style='linear', title=None, rowspan=1, colspan=1):
        """Configure a subplot at position ``position``.
        
        :param position: tuple of two integers, the position of the subplot in the layout.
        :param xlim: tuple of two floats, the limits of the x-axis. If not given, the limits are set to ``(0, 1)``.
        :param ylim: tuple of two floats, the limits of the y-axis.
        :param t_span: int/float, the length of the time axis. If this option is not specified, it is computed from the ``xlim``.
        :param axis_style: string, the style of the axis. Can be "linear", "semilogx", "semilogy" or "loglog".
        :param title: string, the title of the subplot.
        :param rowspan: int, the number of rows the subplot spans. Default is 1.
        :param colspan: int, the number of columns the subplot spans. Default is 1.
        """
        self.subplot_options[position] = {}

        if xlim is not None:
            self.subplot_options[position]['xlim'] = xlim
        if ylim is not None:
            self.subplot_options[position]['ylim'] = ylim
        if t_span is not None:
            self.subplot_options[position]['t_span'] = t_span
        if axis_style is not None:
            self.subplot_options[position]['axis_style'] = axis_style
        if title is not None:
            self.subplot_options[position]['title'] = title
        if rowspan is not None:
            self.subplot_options[position]['rowspan'] = rowspan
        if colspan is not None:
            self.subplot_options[position]['colspan'] = colspan

        if not check_subplot_options_validity(self.subplot_options, self.plots):
            raise ValueError("Invalid subplot options. Check the `rowspan` and `colspan` values.")


    def check(self):
        self.check_subplot_options()

        self.check_added_lines()

    
    def run(self, core):
        self.core = core
        # self.core.is_running_global = False

        self.check()

        # Create the ring buffers for each acquisition.
        self.create_ring_buffers()

        # Start the QT application.
        self.app = QApplication.instance()
        if self.app is None:
            self.app = QApplication(sys.argv)

        with self.app:
            self.main_window = MainWindow(self, self.core, self.app)
            self.main_window.show()
            self.app.exec_()


    def check_added_lines(self):
        if self.plots is None:
            raise ValueError("No plots were added to the visualization. Use the `add_lines` method to add plots.")

        n_lines = sum([len(plot_channels) for plot_channels in self.plots.values()])
        
        if hasattr(self, "core"):
            # Determine the nth value for each line.
            for source, plot_channels in self.plots.items():
                acq_index = self.core.acquisition_names.index(source)
                sample_rate = self.core.acquisitions[acq_index].sample_rate
                for i, plot_channel in enumerate(plot_channels):
                    if plot_channel['nth'] == 'auto':
                        pos = plot_channel['pos']
                        t_span = self.subplot_options[pos]['t_span']
                        self.plots[source][i]['nth'] = compute_nth(self.max_points_to_refresh, t_span, n_lines, sample_rate)


    def check_subplot_options(self):
        self.positions = list(set([plot['pos'] for plot in [plot for plots in self.plots.values() for plot in plots]]))[::-1]
        self.positions = [_ for _ in self.positions if _ != 'image']

        # Make sure that all subplots have options defined.
        for pos in self.positions:
            if pos not in self.subplot_options.keys():
                self.subplot_options[pos] = {"xlim": (0, 1), "axis_style": "linear"}

        for pos, options in self.subplot_options.items():
            # Check that all subplots have `t_span` and `xlim` defined.
            if 'xlim' in options.keys() and 't_span' not in options.keys():
                self.subplot_options[pos]['t_span'] = options['xlim'][1] - options['xlim'][0]
            elif 't_span' in options.keys() and 'xlim' not in options.keys():
                self.subplot_options[pos]['xlim'] = (0, options['t_span'])
            elif 'xlim' not in options.keys() and 't_span' not in options.keys():
                self.subplot_options[pos]['xlim'] = (0, 1)
                self.subplot_options[pos]['t_span'] = 1
            else:
                pass


    def create_ring_buffers(self):
        self.ring_buffers = {}
        for source in self.plots.keys():
            if hasattr(self.core.acquisitions[self.core.acquisition_names.index(source)], 'image_shape'):
                n_channels = 1
                rows = 1

                # number of lines added with this source. If no lines are added, then n_channels is 1.
                # n_channels = max(1, sum([len(_['channels']) for _ in self.plots[source] if _['pos'] != 'image']))
                # rows = ...
            else:
                acq = self.core.acquisitions[self.core.acquisition_names.index(source)]
                rows = int(max([self.subplot_options[pos]['t_span'] * acq.sample_rate for pos in self.positions]))
                n_channels = acq.n_channels

            self.ring_buffers[source] = RingBuffer2D(rows, n_channels)


class MainWindow(QMainWindow):
    def __init__(self, vis, core, app):
        super().__init__()
        
        self.vis = vis
        self.core = core
        self.app = app

        script_directory = os.path.dirname(os.path.realpath(__file__))
        icon_path = os.path.join(script_directory, "../logo.png")
        app_icon = QIcon(icon_path)
        self.setWindowIcon(app_icon)

        self.triggered = False
        self.measurement_stopped = False
        self.freeze_plot = False

        self.setWindowTitle('Data Acquisition and Visualization')
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout_widget = QHBoxLayout(self.central_widget)
        self.layout_widget.setContentsMargins(20, 20, 20, 20) # set the padding

        self.desktop = QDesktopWidget().screenGeometry()
        if hasattr(self.vis, 'last_position'):
            self.move(self.vis.last_position)
            self.resize(self.vis.last_size)
        else:
            self.resize(int(self.desktop.width()*0.95), int(self.desktop.height()*0.8))

            window_geometry = self.frameGeometry()
            center_offset = self.desktop.center() - window_geometry.center()
            self.move(self.pos() + center_offset)

        self.add_buttons()

        self.init_plots()

        self.init_timer()


    def add_buttons(self):
        self.button_layout = QVBoxLayout()
        self.button_layout.setContentsMargins(5, 5, int(self.desktop.width()*0.01), 5)

        self.trigger_button = QPushButton('Start Measurement')
        self.trigger_button.clicked.connect(self.trigger_measurement)
        self.button_layout.addWidget(self.trigger_button)

        self.close_button = QPushButton('Close')
        self.close_button.clicked.connect(self.close_app)
        self.button_layout.addWidget(self.close_button)

        self.full_screen_button = QPushButton('Full Screen')
        self.full_screen_button.clicked.connect(self.toggle_full_screen)
        self.button_layout.addWidget(self.full_screen_button)

        self.legend_button = QPushButton('Toggle Legends')
        self.legend_button.clicked.connect(self.toggle_legends)
        self.button_layout.addWidget(self.legend_button)

        self.freeze_button = QPushButton('Freeze')
        self.freeze_button.clicked.connect(self.toggle_freeze_plot)
        self.button_layout.addWidget(self.freeze_button)

        label = QLabel(self)
        label.setText("Measurement status:")
        self.button_layout.addWidget(label)

        self.label = QLabel(self)
        self.label.setText("Not started.")
        self.button_layout.addWidget(self.label)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(0)
        self.progress_bar.setOrientation(Qt.Vertical)

        self.progress_bar.setStyleSheet("""
            QProgressBar {
                width: 100px;
                height: 500px;
                padding: 0px;
                align: center;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #05B8CC;
            }
        """)

        self.button_layout.addStretch(1)

        self.button_layout.addWidget(self.progress_bar)

        self.layout_widget.addLayout(self.button_layout)


    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Q:
            if self.measurement_stopped:
                self.close_app()
            else:
                self.stop_measurement(mode='manual')

        elif event.key() == Qt.Key_S:
            self.core.start_acquisition()
        
        elif event.key() == Qt.Key_F:
            self.toggle_freeze_plot()
        
        elif event.key() == Qt.Key_L:
            self.toggle_legends()

        elif event.key() == Qt.Key_F11:
            self.toggle_full_screen()

    
    def init_plots(self):
        # Compute the update refresh rate
        n_lines = sum([len(plot_channels) for plot_channels in self.vis.plots.values()])
        minimum_refresh_rate = int(min(list(set([plot['refresh_rate'] for plot in [plot for plots in self.vis.plots.values() for plot in plots]]))))
        
        # Compute the max number of plots per refresh (if sequential plot updates are enabled)
        if self.vis.sequential_plot_updates:
            # Max number of plots per refresh is computed
            computed_update_refresh_rate = max(10, min(500, int(minimum_refresh_rate/(n_lines+1))))
            self.vis.max_plots_per_refresh = int(np.ceil((n_lines * computed_update_refresh_rate) / minimum_refresh_rate))
            self.vis.update_refresh_rate = computed_update_refresh_rate
        else:
            self.vis.max_plots_per_refresh = 1e40
            self.vis.update_refresh_rate = minimum_refresh_rate


        pg.setConfigOption('background', 'w')
        pg.setConfigOption('foreground', 'k')

        self.time_start = time.time()
        grid_layout = pg.GraphicsLayoutWidget()

        self.subplots = {}
        self.legends = {}

        if self.vis.add_line_widget:
            self.layout_widget.addWidget(grid_layout, stretch=1)
        
        if self.vis.add_image_widget:
            if self.vis.color_map == 'CET-L17':
                cm = pg.colormap.get(self.vis.color_map)
            else:
                cm = pg.colormap.getFromMatplotlib(self.vis.color_map)
            if cm.color[0, 0] == 1:
                cm.reverse()
            self.image_view = ImageView()
            self.image_view.setColorMap(cm)
            self.layout_widget.addWidget(self.image_view, stretch=1)
            self.image_view.ui.histogram.hide()
            self.image_view.ui.roiBtn.hide()
            self.image_view.ui.menuBtn.hide()

        color_dict = {}
        ##################################################################
        
        # Create subplots
        for pos in self.vis.positions:
            if pos not in self.subplots.keys():
                if 'rowspan' in self.vis.subplot_options[pos].keys():
                    rowspan = self.vis.subplot_options[pos]['rowspan']
                else:
                    rowspan = 1
                
                if 'colspan' in self.vis.subplot_options[pos].keys():
                    colspan = self.vis.subplot_options[pos]['colspan']
                else:
                    colspan = 1

                if 'title' in self.vis.subplot_options[pos].keys():
                    title = self.vis.subplot_options[pos]['title']
                else:
                    title = None

                self.subplots.update({pos: grid_layout.addPlot(*pos, rowspan=rowspan, colspan=colspan, title=title)})

                if pos in self.vis.subplot_options.keys():
                    options = self.vis.subplot_options[pos]
                    transform_lim_x = lambda x: x
                    transform_lim_y = lambda x: x
                    if 'axis_style' in options:
                        if options['axis_style'] == 'semilogy':
                            self.subplots[pos].setLogMode(y=True)
                            transform_lim_y = lambda x: np.log10(x)
                        elif options['axis_style'] == 'semilogx':
                            self.subplots[pos].setLogMode(x=True)
                            transform_lim_x = lambda x: np.log10(x)
                        elif options['axis_style'] == 'loglog':
                            self.subplots[pos].setLogMode(x=True, y=True)
                        elif options['axis_style'] == 'linear':
                            self.subplots[pos].setLogMode(y=False)

                    if 'xlim' in options:
                        self.subplots[pos].setXRange(transform_lim_x(options['xlim'][0]), transform_lim_x(options['xlim'][1]))
                    if 'ylim' in options:
                        self.subplots[pos].setYRange(transform_lim_y(options['ylim'][0]), transform_lim_y(options['ylim'][1]))
                
        # Create lines for each plot channel
        for source, plot_channels in self.vis.plots.items():
            channel_names = self.core.acquisitions[self.core.acquisition_names.index(source)].channel_names
            color_dict.update({ch: ind+len(color_dict) for ind, ch in enumerate(channel_names)})

            for i, plot_channel in enumerate(plot_channels):
                pos = plot_channel['pos']
                ch = plot_channel['channels']
                if isinstance(ch, tuple):
                    x, y = ch
                    line = self.subplots[pos].plot(pen=pg.mkPen(color=color_dict[channel_names[y]], width=2), name=f"{channel_names[x]} vs. {channel_names[y]}")
                    self.vis.plots[source][i]['line'] = line

                elif isinstance(ch, int):
                    line = self.subplots[pos].plot(pen=pg.mkPen(color=color_dict[channel_names[ch]], width=2), name=f"{channel_names[ch]}")
                    self.vis.plots[source][i]['line'] = line

                # Add legend to the subplot
                if pos not in self.legends.keys() and pos != 'image':
                    legend = self.subplots[pos].addLegend()
                    for item in self.subplots[pos].items:
                        if isinstance(item, pg.PlotDataItem):
                            legend.addItem(item, item.opts['name'])
                    self.legends[pos] = legend

        self.plots = self.vis.plots
        

    def init_timer(self):
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_plots)
        self.timer.start(self.vis.update_refresh_rate)


    def update_ring_buffers(self):
        for source, buffer in self.vis.ring_buffers.items():
            if hasattr(self.core.acquisitions[self.core.acquisition_names.index(source)], 'image_shape'):
                plot_channel = self.plots[source][-1]
                since_refresh = plot_channel['since_refresh']
                refresh_rate = plot_channel['refresh_rate']
                # only update if refresh rate is reached
                if (refresh_rate <= since_refresh + self.vis.update_refresh_rate):
                    _, new_data = self.core.acquisitions[self.core.acquisition_names.index(source)].get_data(N_points=1)

                    if len(new_data) > 0:
                        self.new_image = new_data[-1].T

                    # ch = [_['channels'] for _ in self.plots[source] if _['pos'] == 'image']
                    # ch_raweled = [np.ravel_multi_index(_, self.core.acquisitions[self.core.acquisition_names.index(source)].image_shape) for _ in ch]
                    # if not isinstance(ch, str):
                    #     buffer.extend(new_data[source].reshape(new_data[source].shape[0], -1)[ch_raweled])
            else:
                new_data = self.core.acquisitions[self.core.acquisition_names.index(source)].get_data_PLOT()
                buffer.extend(new_data)


    def update_plots(self, force_refresh=False):
        # Stop the measurement if the acquisitions are done and if the measurement has not been stopped.
        if not self.core.is_running_global and not self.measurement_stopped:
            self.stop_measurement()

        # If the emasurement is started, start the timer and update the progress bar.
        if self.core.triggered_globally and not self.triggered:
            self.on_measurement_start()

            if self.core.measurement_duration is not None: 
                self.progress_bar.setMaximum(int(1000*self.core.acquisitions[0].Trigger.N_samples_to_acquire) ) 
            else:
                pass

        # If the measurement is running, update the progress bar and the label.
        if self.triggered and self.core.is_running_global:
            if self.core.measurement_duration is not None:
                self.progress_bar.setValue(int(1000*self.core.acquisitions[0].Trigger.N_acquired_samples_since_trigger))
                string = f"Duration: {self.core.measurement_duration:.1f} s"
            else:
                string = "Duration: Until stopped"
            self.label.setText(string) 

        # Update the ring buffers.
        self.update_ring_buffers()

        if not self.freeze_plot:
            updated_plots = 0
            for source, plot_channels in self.plots.items():
                self.vis.acquisition = self.core.acquisitions[self.core.acquisition_names.index(source)]

                # for line, pos, apply_function, *channels in plot_channels:
                for plot_channel in plot_channels:
                    refresh_rate = plot_channel['refresh_rate']
                    since_refresh = plot_channel['since_refresh']

                    if (refresh_rate <= since_refresh + self.vis.update_refresh_rate or force_refresh) and updated_plots < self.vis.max_plots_per_refresh:
                        # If time to refresh, refresh the plot and set since_refresh to 0.
                        plot_channel['since_refresh'] = 0
                        
                        if plot_channel['pos'] == 'image':
                            if hasattr(self, 'new_image'):
                                new_data = self.new_image#[::5, ::5]
                                # new_data = np.random.rand(200, 200)
                            else:
                                new_data = np.random.rand(200, 200)
                            self.update_image(new_data)
                        else:
                            new_data = self.vis.ring_buffers[source].get_data()
                            self.update_line(new_data, plot_channel)

                        updated_plots += 1
                    else:
                        # If not time to refresh, increase since_refresh by update_refresh_rate.
                        plot_channel['since_refresh'] += self.vis.update_refresh_rate
    
    
    def update_image(self, new_data):
        if hasattr(self, 'boxstate'):
            _view = self.image_view.getView()
            _state = _view.getState()

        self.image_view.setImage(new_data)

        if hasattr(self, 'boxstate'):
            _view.setState(_state)

        self.boxstate = True


    def update_line(self, new_data, plot_channel):
        # only plot data that are within xlim (applies only for normal plot, not ch vs. ch)
        t_span_samples = int(self.vis.subplot_options[plot_channel['pos']]['t_span'] * self.vis.acquisition.sample_rate)
        
        nth = plot_channel['nth']

        xlim = self.vis.subplot_options[plot_channel['pos']]['xlim']

        if isinstance(plot_channel['channels'], int):
            # plot a single channel
            ch = plot_channel['channels']
            fun_return = plot_channel['apply_function'](self.vis, new_data[-t_span_samples:, ch])

            if len(fun_return.shape) == 1: 
                # if function returns only 1D array
                y = fun_return[::nth]
                x = (np.arange(t_span_samples) / self.vis.acquisition.sample_rate)[::nth]

            elif len(fun_return.shape) == 2 and fun_return.shape[1] == 2:  
                # function returns 2D array (e.g. fft returns freq and amplitude)
                # In this case, the first column is the x-axis and the second column is the y-axis.
                # The nth argument is not used in this case.
                x, y = fun_return.T # expects 2D array to be returned

            else:
                raise Exception("Function used in `layout` must return either 1D array or 2D array with 2 columns.")
            
            mask = (x >= xlim[0]) & (x <= xlim[1]) # Remove data outside of xlim
            
            plot_channel['line'].setData(x[mask], y[mask])

        elif isinstance(plot_channel['channels'], tuple): 
            # channel vs. channel
            fun_return = plot_channel['apply_function'](self.vis, new_data[-t_span_samples:, plot_channel['channels']])
            x, y = fun_return.T
            mask = (x >= xlim[0]) & (x <= xlim[1]) # Remove data outside of xlim
            
            plot_channel['line'].setData(x[mask][::nth], y[mask][::nth])

        else:
            raise Exception("A single channel or channel vs. channel plot can be plotted at a time. Got more than 2 channels.")


    def close_app(self):
        self.vis.last_position = self.pos()
        self.vis.last_size = self.size()

        if not self.measurement_stopped:
            self.stop_measurement()

        self.app.quit()
        self.close()

    
    def closeEvent(self, a0):
        """Call close_app() when the user closes the window by pressing the X button."""
        self.close_app()
        return super().closeEvent(a0)


    def stop_measurement(self, mode='finished'):
        #self.core.triggered_globally = True # dummy start measurement
        self.core.stop_acquisition_and_generation()
        self.timer.stop()

        self.trigger_button.setText('Start measurement')
        self.trigger_button.setEnabled(False)
        self.measurement_stopped = True

        # Update the plots one last time.
        self.update_plots(force_refresh=True)

        # palette = self.palette()
        # palette.setColor(self.backgroundRole(), QColor(152, 251, 251))
        # self.setPalette(palette)

        if mode == 'finished':
            self.label.setText(f"Finished.")
            self.progress_bar.setValue(self.progress_bar.maximum())

        if self.core.autoclose:
            self.close_app()


    def trigger_measurement(self):
        if not self.triggered:
            self.core.start_acquisition()
        else:
            self.stop_measurement(mode='manual')
            

    def toggle_full_screen(self):
        if self.isFullScreen():
            self.showNormal()
            self.full_screen_button.setText('Full Screen')
        else:
            self.showFullScreen()
            self.full_screen_button.setText('Exit Full Screen')


    def toggle_legends(self):
        if self.vis.show_legend:
            self.vis.show_legend = False
        else:
            self.vis.show_legend = True

        for pos, legend in self.legends.items():
            legend.setVisible(self.vis.show_legend)


    def on_measurement_start(self):
        self.triggered = True
        self.trigger_button.setText('Stop measurement')
        palette = self.palette()
        palette.setColor(self.backgroundRole(), QColor(152, 251, 177))
        self.setPalette(palette)


    def toggle_freeze_plot(self):
        if self.freeze_plot:
            self.freeze_plot = False
            self.freeze_button.setText('Freeze')
        else:
            self.freeze_plot = True
            self.freeze_button.setText('Unfreeze')


        