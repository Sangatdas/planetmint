# Copyright © 2020 Interplanetary Database Association e.V.,
# Planetmint and IPDB software contributors.
# SPDX-License-Identifier: (Apache-2.0 AND CC-BY-4.0)
# Code is Apache-2.0 and docs are CC-BY-4.0

import logging
import tarantool
from planetmint.common.exceptions import DatabaseDoesNotExist
from planetmint.config import Config
from planetmint.common.exceptions import ConfigurationError

logger = logging.getLogger(__name__)


class TarantoolDB:
    def __init__(self, host: str = "localhost", port: int = 3303, user: str = None, password: str = None,
                 reset_database: bool = False, **kwargs):
        try:
            self.host = host
            self.port = port
            # TODO add user support later on
            print(f"host : {host}")
            print(f"port : {port}")
            # self.db_connect = tarantool.connect(host=host, port=port, user=user, password=password)
            # TODO : raise configuraiton error if the connection cannot be established
            self.db_connect = tarantool.connect(host=self.host, port=self.port)
            self.init_path = Config().get()["database"]["init_config"]["absolute_path"]
            self.drop_path = Config().get()["database"]["drop_config"]["absolute_path"]
            args_reset_db = kwargs.get("kwargs").get("reset_database") if "kwargs" in kwargs else None
            if reset_database or args_reset_db is True:
                self.drop_database()
                self.init_database()
                self._reconnect()
            self.SPACE_NAMES = ["abci_chains", "assets", "blocks", "blocks_tx",
                                "elections", "meta_data", "pre_commits", "validators",
                                "transactions", "inputs", "outputs", "keys"]
        except:
            logger.info('Exception in _connect(): {}')
            raise ConfigurationError

    def _reconnect(self):
        self.db_connect = tarantool.connect(host=self.host, port=self.port)

    def space(self, space_name: str):
        return self.db_connect.space(space_name)

    def get_connection(self):
        return self.db_connect

    def drop_database(self):
        db_config = Config().get()["database"]
        cmd_resp = self.run_command(command=self.drop_path, config=db_config)
        self._reconnect()
        return cmd_resp

    def init_database(self):
        db_config = Config().get()["database"]
        cmd_resp = self.run_command(command=self.init_path, config=db_config)
        self._reconnect()
        return cmd_resp

    def run_command(self, command: str, config: dict):
        from subprocess import Popen, PIPE, run
        print(f" commands: {command}")
        ret = Popen(
            ['%s %s:%s < %s' % ("tarantoolctl connect", self.host, self.port, command)],
            stdin=PIPE,
            stdout=PIPE,
            universal_newlines=True,
            bufsize=1,
            shell=True).stdout  # TODO stdout is not apppearing
        print(f"ret ---- {ret.readlines()} ------")
        return False if "nil value" in ret else True
