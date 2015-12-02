#!/usr/bin/python3
# -*- coding: utf-8 -*-

import copy
import datetime
import itertools
import os
import random
import subprocess
import sys
import mysql.connector as mdb

# To make this work, create a file 'settings.py' which contains the following
# code, adapted to your needs:

'''
import random
import socket

class Settings:
    @staticmethod
    def get_parameters():
        n_variables          = random.randint(2, 5)
        n_ideals             = random.randint(3, 4)
        n_gens_from          = 2
        n_gens_to            = 3
        deg_from             = random.randint(1, 2)
        deg_to               = random.randint(2, 3) 
        percent_entries_zero = random.randint(0, 0)
        percent_terms_zero   = random.randint(95, 99)
        bound_coeffs         = random.randint(10, 500)
        max_size             = random.randint(3, 4)
        return [n_variables, n_ideals, n_gens_from, n_gens_to, deg_from,
            deg_to, percent_entries_zero, percent_terms_zero, bound_coeffs,
            max_size]

    options = [   # the first item in each list is the default
        [0, 1],                      # use_trick
        [1, 0],                      # use_syz_ring
        [1, 0],                      # use_syzComp
        [0, 1],                      # use_redTail
        [0, 1],                      # use_redThrough
       # [0, 2, 32003, 2147483647],   # characteristic
        [0, 32003],                  # characteristic
        [0, 1, 2],                   # ordering
        [0, 1]                       # precompute_stds
    ]

    omissions = [
        [[1, 0], [6, 1]],   # no syz_ring and ordering (dp, c)
        [[1, 0], [6, 2]]    # no syz_ring and ordering (dp, C)
    ]

    database_config = dict(
        host     = "",
        user     = "",
        password = "",
        database = ""
    )

    cas           = "Singular"
    cas_directory = ""
    cas_binary    = ""

    @staticmethod
    def cas_command(binary, script, parameters, seed):
        if seed is not None:
            command = binary+" -q -r "+seed+" -u "+parameters+" "+script
        else:
            command = binary+" -q -u "+parameters+" "+script
        return command

    script_directory        = ""
    script_generate_example = "generate_random_example"
    script_run_example      = "run_example"

    @staticmethod
    def server():
        return socket.gethostname().split(".")[0]
'''

dont_write_bytecode_safe = sys.dont_write_bytecode
sys.dont_write_bytecode = True
from settings import *
sys.dont_write_bytecode = dont_write_bytecode_safe

class Tuple(tuple):
    def __init__(self, data):
        self.data = data

    def __str__(self):
        return self.string()

    def string(self):
        return ",".join(map(str, self.data))

    def tuple(self):
        return self.data

class Options:
    def __init__(self):
        # actually, deepcopy is not really necessary here:
        self._options = copy.deepcopy(Settings.options)
        self._omissions = copy.deepcopy(Settings.omissions)
        self._iterator =  itertools.product(*self._options)

    def __iter__(self):
        return self

    def __next__(self):
        next = self._iterator.__next__()
        while not self._isValid(next):
            next = self._iterator.__next__()
        return Tuple(next)

    def _isValid(self, next):
        for o in self._omissions:
            if (next[o[0][0]] == o[0][1] and next[o[1][0]] == o[1][1]):
                return False
        return True
        
    @staticmethod
    def count():
        return sum(1 for _ in Options())

class Database:
    def open(self):
        try:
            self._connection = mdb.connect(**Settings.database_config)
        except mdb.Error as error:
            print("Error: {}".format(error))

    def execute(self, operation):
        try:
            cursor = self._connection.cursor()
            cursor.execute(operation)
            self._connection.commit()
            self.lastrowid = cursor.lastrowid
            cursor.close()
        except mdb.Error as error:
            print("Error: {}".format(error))

    def close(self):
        self._connection.close()

class Example:
    def create(self):
        self.parameters = ",".join(map(str, Settings.get_parameters()))
        seed = str(random.randint(-2147483648, 2147483647))
        command = Settings.cas_command(Settings.cas_binary,
            Settings.script_generate_example, self.parameters, seed)
        try:
            example = subprocess.check_output(command, shell=True) \
                .decode("utf-8").splitlines()
        except subprocess.CalledProcessError as error:
            print("Error: {}".format(error))
        self.variables = example[0]
        self.n_components = example[1]
        self.components = "\n".join(example[2:])
        self.script_hash = git_hash(Settings.script_directory)

    def save(self):
        if len(self.intersection) < 65536:   # max. size of mariadb type 'text'
            intersection = self.intersection
        else:
            intersection = "NULL"
        operation = "INSERT INTO examples " \
            +"(variables, n_components, components, intersection, " \
            +"script_hash, parameters) " \
            +"VALUES ('{}', {}, \n'{}', \n'{}', \n'{}', \n'{}')" \
            .format(self.variables, self.n_components, self.components,
            intersection, self.script_hash, self.parameters)
        self._database.execute(operation)
        self.id = self._database.lastrowid

    def run(self):
        options = Options()
        defaults = next(options)   # first entry: defaults
        timing = Timing(self, defaults)
        while not timing.succeeded:
            self.create()
            timing.compute()
        self._database = Database()
        self._database.open()
        self.save()
        timing.save()
        for opt in options:   # the rest of the options
            timing = Timing(self, opt)
            timing.compute()
            timing.save()
        self._database.close

class Timing:
    def __init__(self, example, opt):
        self.example = example
        self.opt = opt
        self.succeeded = False
        self.cas = Settings.cas
        self.cas_hash = git_hash(Settings.cas_directory)
        self.script_hash = git_hash(Settings.script_directory)
        self.server = Settings.server()
        
    def compute(self):
        self.time = datetime.datetime.utcnow()
        filename = "intersect_"+self.cas+"_"+self.server+"_"+str(os.getpid()) \
            +"_"+str(self.time.timestamp())
        with open(filename, "w") as file:
            file.write(self.opt.string()+"\n")
            file.write(self.example.variables+"\n")
            file.write(self.example.n_components+"\n")
            file.write(self.example.components+"\n")
            if hasattr(self.example, "intersection"):
                file.write(self.example.intersection+"\n")
            else:
                file.write("\n")
        command = Settings.cas_command(Settings.cas_binary,
            Settings.script_run_example, '"\\"'+filename+'\\""', None)
        try:
            output = subprocess.check_output(command, shell=True,
                timeout=86400).decode("utf-8").splitlines()
            self.succeeded = True
            if not hasattr(self.example, "intersection"):
                self.example.intersection = output[-1]
            self.time_stds = output[0]
            self.time_intersect = output[1]
            self.n_generators = output[2]
        except subprocess.TimeoutExpired:
            self.time_stds = "NULL"
            self.time_intersect = "NULL"
            self.n_generators = "NULL"
        except subprocess.CalledProcessError as error:
            print("Error: {}".format(error))
        finally:
            os.remove(filename)

    def save(self):
        operation = ("INSERT INTO timings " \
            +"(example_id, use_trick, use_syz_ring, use_syzComp, " \
            +"use_redTail, use_redThrough, characteristic, ordering, " \
            +"precompute_stds, time_stds, time_intersect, n_generators, " \
            +"cas, cas_hash, script_hash, server, time) " \
            +"VALUES ({0}, {9}, {10}, {11}, {12}, {13}, {14}, {15}, {16}, " \
            +"{1}, {2}, {3}, '{4}', '{5}', '{6}', '{7}', '{8}')") \
            .format(self.example.id, self.time_stds, self.time_intersect,
            self.n_generators, self.cas, self.cas_hash, self.script_hash,
            self.server, self.time, *self.opt.tuple())
        self.example._database.execute(operation)

def git_hash(directory):
    command = "cd "+directory+" && git rev-parse --verify HEAD"
    try:
        output = subprocess.check_output(command, shell=True).decode("utf-8") \
            .splitlines()[0]
    except subprocess.CalledProcessError as error:
        print("Error: {}".format(error))
    return output

while True:
    example = Example()
    example.run()

sys.exit()
