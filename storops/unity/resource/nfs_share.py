# Copyright (c) 2015 EMC Corporation.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from __future__ import unicode_literals

import logging

from storops.unity.enums import NFSShareDefaultAccessEnum
import storops.unity.resource.filesystem
from storops.unity.resource import UnityResource, UnityResourceList

__author__ = 'Jay Xu'

LOG = logging.getLogger(__name__)


class UnityNfsShare(UnityResource):
    @classmethod
    def create(cls, cli, name, fs, path=None, share_access=None):
        fs_clz = storops.unity.resource.filesystem.UnityFileSystem
        fs = fs_clz.get(cli, fs).verify()
        NFSShareDefaultAccessEnum.verify(share_access)
        sr = fs.storage_resource

        if path is None:
            path = '/'

        share_param = cli.make_body(defaultAccess=share_access)
        param = cli.make_body(name=name, path=path,
                              nfsShareParameters=share_param)
        resp = sr.modify_fs(nfsShareCreate=[param])
        resp.raise_if_err()
        return UnityNfsShareList(cli=cli, name=name).first_item

    def remove(self):
        fs = self.filesystem.verify()
        sr = fs.storage_resource
        param = self._cli.make_body(nfsShare=self)
        resp = sr.modify_fs(nfsShareDelete=[param])
        resp.raise_if_err()
        return resp


class UnityNfsShareList(UnityResourceList):
    @classmethod
    def get_resource_class(cls):
        return UnityNfsShare
