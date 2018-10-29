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

import retryz

import storops.unity.resource.move_session
import storops.unity.resource.pool
from storops.exception import UnityBaseHasThinCloneError, \
    UnityResourceNotFoundError, UnityCGMemberActionNotSupportError, \
    UnityThinCloneNotAllowedError, UnityMigrationSourceHasThinCloneError, \
    UnityMigrationTimeoutException
from storops.lib.thinclone_helper import TCHelper
from storops.lib.version import version
from storops.unity import enums
from storops.unity.client import UnityClient
from storops.unity.enums import TieringPolicyEnum, NodeEnum, \
    HostLUNAccessEnum, ThinCloneActionEnum, StorageResourceTypeEnum
from storops.unity.resource import UnityResource, UnityResourceList
from storops.unity.resource.host import UnityHostList
from storops.unity.resource.snap import UnitySnap, UnitySnapList
from storops.unity.resource.sp import UnityStorageProcessor
from storops.unity.resource.storage_resource import UnityStorageResource
from storops.unity.resp import RESP_OK

__author__ = 'Jay Xu'

log = logging.getLogger(__name__)


def prepare_lun_parameters(cli=None, **kwargs):
    @version('<4.3')
    def make_compression_body(cli=None,
                              is_compression=None):
        return UnityClient.make_body(isCompressionEnabled=is_compression)

    @version('>=4.3')  # noqa
    def make_compression_body(cli=None,
                              is_compression=None):
        return UnityClient.make_body(isDataReductionEnabled=is_compression)

    sp = kwargs.get('sp')
    if isinstance(sp, UnityStorageProcessor):
        sp_node = sp.to_node_enum()
    elif isinstance(sp, NodeEnum):
        sp_node = sp
    else:
        sp_node = NodeEnum.parse(sp)
    NodeEnum.verify(sp_node)

    TieringPolicyEnum.verify(kwargs.get('tiering_policy'))

    lun_parameters = UnityClient.make_body(
        isThinEnabled=kwargs.get('is_thin'),
        size=kwargs.get('size'),
        pool=kwargs.get('pool'),
        defaultNode=sp_node,
        fastVPParameters=UnityClient.make_body(
            tieringPolicy=kwargs.get('tiering_policy')),
        ioLimitParameters=UnityClient.make_body(
            ioLimitPolicy=kwargs.get('io_limit_policy')))

    compression_body = make_compression_body(
        cli,
        kwargs.get('is_compression'))

    lun_parameters.update(compression_body)

    # Empty host access can be used to wipe the host_access
    host_access = UnityClient.make_body(kwargs.get('host_access'),
                                        allow_empty=True)

    if host_access is not None:
        lun_parameters['hostAccess'] = host_access
    return lun_parameters


class UnityLun(UnityResource):
    _is_cg_member = None
    _cg = None

    @classmethod
    def get_nested_properties(cls):
        return (
            'pool.name',
            'pool.raid_type',
            'pool.isFASTCacheEnabled',
            'host_access.host.name',
            'storage_resource.type'  # To avoid query parent type
        )

    @classmethod
    def create(cls, cli, name, pool, size, sp=None, host_access=None,
               is_thin=None, description=None, io_limit_policy=None,
               is_repl_dst=None, tiering_policy=None, snap_schedule=None,
               is_compression=None):
        pool_clz = storops.unity.resource.pool.UnityPool
        pool = pool_clz.get(cli, pool)

        req_body = cls._compose_lun_parameter(
            cli, name=name, pool=pool, size=size, sp=sp, is_thin=is_thin,
            host_access=host_access, description=description,
            io_limit_policy=io_limit_policy, is_repl_dst=is_repl_dst,
            tiering_policy=tiering_policy, snap_schedule=snap_schedule,
            is_compression=is_compression)
        resp = cli.type_action(UnityStorageResource().resource_class,
                               'createLun', **req_body)
        resp.raise_if_err()
        sr = UnityStorageResource(_id=resp.resource_id, cli=cli)
        return sr.luns[0]

    @property
    def name(self):
        if hasattr(self, '_name') and self._name is not None:
            name = self._name
        else:
            if not self._is_updated():
                self.update()
            name = self._get_value_by_key('name')
        return name

    @name.setter
    def name(self, new_name):
        self.modify(name=new_name)

    @property
    def is_cg_member(self):
        if self._is_cg_member is None:  # None means unknown, requires a query
            return (self.storage_resource.type ==
                    StorageResourceTypeEnum.CONSISTENCY_GROUP)
        else:
            return self._is_cg_member

    @is_cg_member.setter
    def is_cg_member(self, is_cg_member):
        self._is_cg_member = is_cg_member

    @property
    def cg(self):
        if self.is_cg_member and self._cg is None:
            from storops.unity.resource.cg import UnityConsistencyGroup
            self._cg = UnityConsistencyGroup(cli=self._cli,
                                             _id=self.storage_resource.id)
        return self._cg

    @property
    def io_limit_rule(self):
        rule = None
        if self.io_limit_policy:
            policy = self.io_limit_policy
            if policy.io_limit_rule_settings:
                rules = policy.io_limit_rule_settings
            elif policy.io_limit_rules:
                rules = policy.io_limit_rules
            else:
                rules = None

            if rules:
                rule = rules[0]
        return rule

    @property
    def total_size_gb(self):
        return self.size_total / (1024 ** 3)

    @total_size_gb.setter
    def total_size_gb(self, value):
        self.expand(value * 1024 ** 3)

    @property
    def max_iops(self):
        return self.effective_io_limit_max_iops

    @property
    def max_kbps(self):
        return self.effective_io_limit_max_kbps

    def expand(self, new_size):
        """ expand the LUN to a new size

        :param new_size: new size in bytes.
        :return: the old size
        """
        ret = self.size_total
        resp = self.modify(size=new_size)
        resp.raise_if_err()
        return ret

    @staticmethod
    def _compose_lun_parameter(cli, **kwargs):

        # TODO: snap_schedule
        body = cli.make_body(
            name=kwargs.get('name'),
            description=kwargs.get('description'),
            replicationParameters=cli.make_body(
                isReplicationDestination=kwargs.get('is_repl_dst')))

        # `hostAccess` could be empty list which is used to remove all host
        # access
        lun_parameters = prepare_lun_parameters(cli, **kwargs)
        if lun_parameters:
            body['lunParameters'] = lun_parameters
        return body

    def modify(self, name=None, size=None, host_access=None,
               description=None, sp=None, io_limit_policy=None,
               is_repl_dst=None, tiering_policy=None, snap_schedule=None,
               is_compression=None):
        if self.is_cg_member:
            if is_repl_dst is not None or snap_schedule is not None:
                log.warning('LUN in CG not support to modify `is_repl_dst` and'
                            ' `snap_schedule`.')
            return self.cg.modify_lun(self, name=name, size=size,
                                      host_access=host_access,
                                      description=description, sp=sp,
                                      io_limit_policy=io_limit_policy,
                                      tiering_policy=tiering_policy,
                                      is_compression=is_compression)

        else:
            req_body = self._compose_lun_parameter(
                self._cli, name=name, pool=None, size=size, sp=sp,
                host_access=host_access, description=description,
                io_limit_policy=io_limit_policy, is_repl_dst=is_repl_dst,
                tiering_policy=tiering_policy, snap_schedule=snap_schedule,
                is_compression=is_compression)
            resp = self._cli.action(UnityStorageResource().resource_class,
                                    self.get_id(), 'modifyLun', **req_body)
            resp.raise_if_err()
            return resp

    def delete(self, async=False, force_snap_delete=False,
               force_vvol_delete=False):
        sr = self.storage_resource
        if not self.existed or sr is None:
            raise UnityResourceNotFoundError(
                'cannot find lun {}.'.format(self.get_id()))
        resp = self._cli.delete(sr.resource_class, self.get_id(),
                                forceSnapDeletion=force_snap_delete,
                                forceVvolDeletion=force_vvol_delete,
                                async=async)
        try:
            resp.raise_if_err()
        except UnityBaseHasThinCloneError:
            log.warning('cannot delete the lun: %s, because it is a base lun '
                        'of a thin-clone.', self.get_id())
            TCHelper.notify(self, ThinCloneActionEnum.BASE_LUN_DELETE)
            return RESP_OK

        if self.is_thin_clone:
            TCHelper.notify(self, ThinCloneActionEnum.TC_DELETE)
        return resp

    def _attach_to(self, host, access_mask, hlu):
        host_access = [{'host': host, 'accessMask': access_mask}]
        if hlu is not None:
            host_access[0]['hlu'] = hlu
        # If this lun has been attached to other host, don't overwrite it.
        if self.host_access:
            host_access += [{'host': item.host,
                             'accessMask': item.access_mask} for item
                            in self.host_access if host.id != item.host.id]

        resp = self.modify(host_access=host_access)
        resp.raise_if_err()
        log.debug('Notify TCHelper the attaching action of lun: %s.',
                  self.get_id())
        TCHelper.notify(self, ThinCloneActionEnum.LUN_ATTACH)
        return resp

    @version('<4.4.0')  # noqa
    def attach_to(self, host, access_mask=HostLUNAccessEnum.PRODUCTION):
        return self._attach_to(host, access_mask, None)

    @version('>=4.4.0')  # noqa
    def attach_to(self, host, access_mask=HostLUNAccessEnum.PRODUCTION,
                  hlu=None):
        return self._attach_to(host, access_mask, hlu)

    def detach_from(self, host):
        if self.host_access is None:
            return None

        if host is None:
            # Detach the lun from all hosts if `host` is None
            log.info('Detach lun - %s from all hosts.', self.get_id())
            new_access = []
        else:
            new_access = [{'host': item.host,
                           'accessMask': item.access_mask} for item
                          in self.host_access if host.id != item.host.id]
        resp = self.modify(host_access=new_access)
        resp.raise_if_err()
        return resp

    def update_hosts(self, host_names):

        """Primarily for puppet-unity use.

        Update the hosts for the lun if needed.

        :param host_names: specify the new hosts which access the LUN.
        """

        if self.host_access:
            curr_hosts = [access.host.name for access in self.host_access]
        else:
            curr_hosts = []

        if set(curr_hosts) == set(host_names):
            log.info('Hosts for updating is equal to current hosts, '
                     'skip modification.')
            return None

        new_hosts = [UnityHostList.get(cli=self._cli, name=host_name)[0]
                     for host_name in host_names]
        new_access = [{'host': item,
                       'accessMask': HostLUNAccessEnum.PRODUCTION}
                      for item in new_hosts]
        resp = self.modify(host_access=new_access)
        resp.raise_if_err()
        return resp

    def create_snap(self, name=None, description=None, is_auto_delete=None,
                    retention_duration=None):
        if self.is_cg_member:
            raise UnityCGMemberActionNotSupportError()
        return UnitySnap.create(self._cli, self.storage_resource,
                                name=name, description=description,
                                is_auto_delete=is_auto_delete,
                                retention_duration=retention_duration,
                                is_read_only=None, fs_access_type=None)

    @version(">=4.2")
    def thin_clone(self, name, io_limit_policy=None, description=None):
        if self.is_cg_member:
            raise UnityCGMemberActionNotSupportError()

        if not self.is_thin_enabled:
            raise UnityThinCloneNotAllowedError()

        return TCHelper.thin_clone(self._cli, self, name, io_limit_policy,
                                   description)

    def _is_move_session_supported(self, dest):
        if self.is_thin_clone:
            log.error('Not support move session, source lun is thin clone.')
            return False
        if self.is_data_reduction_enabled and not dest.is_all_flash:
            log.error('Not support move session, source lun is compressed, '
                      'but destination pool is not all flash pool.')
            return False
        return True

    def migrate(self, dest, **kwargs):
        if not self._is_move_session_supported(dest):
            return False

        interval = kwargs.pop('interval', 5)
        timeout = kwargs.pop('timeout', 1800)

        @retryz.retry(timeout=timeout, wait=interval,
                      on_return=lambda x: not isinstance(x, bool))
        def _do_check_move_session(move_session_id):
            move_session = clz.get(self._cli, _id=move_session_id)
            if move_session.state == enums.MoveSessionStateEnum.COMPLETED:
                return True
            if move_session.state in [enums.MoveSessionStateEnum.FAILED,
                                      enums.MoveSessionStateEnum.CANCELLED]:
                return False

        clz = storops.unity.resource.move_session.UnityMoveSession
        is_compressed = self.is_data_reduction_enabled

        try:
            move_session = clz.create(self._cli, self, dest,
                                      is_data_reduction_applied=is_compressed)
            return _do_check_move_session(move_session.id)
        except UnityMigrationSourceHasThinCloneError:
            log.error('Not support move session, source lun has thin clone.')
            return False
        except retryz.RetryTimeoutError:
            raise UnityMigrationTimeoutException()

    # `__getstate__` and `__setstate__` are used by Pickle.
    def __getstate__(self):
        return {'_id': self.get_id(), 'cli': self._cli}

    def __setstate__(self, state):
        self.__init__(**state)

    @property
    def snapshots(self):
        return UnitySnapList(cli=self._cli,
                             storage_resource=self.storage_resource)


class UnityLunList(UnityResourceList):
    @classmethod
    def get_resource_class(cls):
        return UnityLun
