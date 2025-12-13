"""
Module for decman configuration options.

NOTE: Do NOT use from imports as global variables might not work as you expect.

Only use:

import decman.config

or

import decman.config as whatever

-- Configuring commands --

Commands are stored as methods in the Commands-class.
The global variable 'commands' of this module is an instance of the Commands-class.

To change the defalts, create a new child class of the Commands-class and set the 'commands'
variable to an instance of your class. Look in the example directory for an example.
"""

debug_output: bool = False
quiet_output: bool = False
color_output: bool = True

pkg_cache_dir: str = "/var/cache/decman"
module_on_disable_scripts_dir: str = "/var/lib/decman/scripts/"
