# Copyright (c) 2018 Dell Inc. or its subsidiaries.
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

from storops.unity.resource import UnityResource, UnityResourceList

__author__ = 'Ryan Liang'

log = logging.getLogger(__name__)


class UnityLunMemberReplication(object):
    def __init__(self, src_lun_id, dst_lun_id, src_status, network_status,
                 dst_status):
        self.src_lun_id = src_lun_id
        self.dst_lun_id = dst_lun_id
        self.src_status = src_status
        self.network_status = network_status
        self.dst_status = dst_status

    def to_json(self):
        return {'srcLunId': self.src_lun_id,
                'dstLunId': self.dst_lun_id,
                'srcStatus': self.src_status,
                'dstStatus': self.dst_status,
                'networkStatus': self.network_status}


class UnitySnapReplicationPolicy(object):
    def __init__(self, is_replicating_snaps, is_retention_same_as_source,
                 is_auto_delete, retention_duration):
        self.is_replicating_snaps = is_replicating_snaps
        self.is_retention_same_as_source = is_retention_same_as_source
        self.is_auto_delete = is_auto_delete
        self.retention_duration = retention_duration

    def to_json(self):
        return {'isReplicatingSnaps': self.is_replicating_snaps,
                'isRetentionSameAsSource': self.is_retention_same_as_source,
                'isAutoDelete': self.is_auto_delete,
                'retentionDuration': self.retention_duration}


class UnityReplicationSession(UnityResource):

    @classmethod
    def create(cls, cli, src_resource_id, dst_resource_id, max_timeout_of_sync,
               name=None, members=None, auto_initiate=None,
               hourly_snap_replication_policy=None,
               daily_snap_replication_policy=None,
               replicate_existing_snaps=None, remote_system=None,
               src_spa_interface=None, src_spb_interface=None,
               dst_spa_interface=None, dst_spb_interface=None):
        """
        Creates a replication session.
        :param cli: the rest cli.
        :param src_resource_id: id of the replication source, could be
            lun/fs/cg.
        :param dst_resource_id: id of the replication destination.
        :param max_timeout_of_sync: maximum time to wait before syncing the
            source and destination. Value `-1` means the automatic sync is not
            performed. `0` means it is a sync replication.
        :param name: name of the replication.
        :param members: list of `UnityLunMemberReplication` object. If
            `src_resource` is cg, `lunMemberReplication` list need to pass in
            to this parameter as member lun pairing between source and
            destination cg.
        :param auto_initiate: indicates whether to perform the first
            replication sync automatically.
            True - perform the first replication sync automatically.
            False - perform the first replication sync manually.
        :param hourly_snap_replication_policy: `UnitySnapReplicationPolicy`
            object. The policy for replicating hourly scheduled snaps of the
            source resource.
        :param daily_snap_replication_policy: `UnitySnapReplicationPolicy`
            object. The policy for replicating daily scheduled snaps of the
            source resource.
        :param replicate_existing_snaps: indicates whether or not to replicate
            snapshots already existing on the resource.
        :param remote_system: `UnityRemoteSystem` object. The remote system of
            remote replication.
        :param src_spa_interface: `UnityRemoteInterface` object. The
            replication interface for source SPA.
        :param src_spb_interface: `UnityRemoteInterface` object. The
            replication interface for source SPB.
        :param dst_spa_interface: `UnityRemoteInterface` object. The
            replication interface for destination SPA.
        :param dst_spb_interface: `UnityRemoteInterface` object. The
            replication interface for destination SPB.
        :return: the newly created replication session.
        """

        req_body = cli.make_body(
            srcResourceId=src_resource_id, dstResourceId=dst_resource_id,
            maxTimeOutOfSync=max_timeout_of_sync, members=members,
            autoInitiate=auto_initiate, name=name,
            hourlySnapReplicationPolicy=hourly_snap_replication_policy,
            dailySnapReplicationPolicy=daily_snap_replication_policy,
            replicateExistingSnaps=replicate_existing_snaps,
            remoteSystem=remote_system,
            srcSPAInterface=src_spa_interface,
            srcSPBInterface=src_spb_interface,
            dstSPAInterface=dst_spa_interface,
            dstSPBInterface=dst_spb_interface)

        resp = cli.post(cls().resource_class, **req_body)
        resp.raise_if_err()
        return cls.get(cli, resp.resource_id)

    def modify(self, max_timeout_of_sync=None, name=None,
               hourly_snap_replication_policy=None,
               daily_snap_replication_policy=None,
               src_spa_interface=None, src_spb_interface=None,
               dst_spa_interface=None, dst_spb_interface=None):
        """
        Modifies properties of a replication session.

        :param max_timeout_of_sync: same as the one in `create` method.
        :param name: same as the one in `create` method.
        :param hourly_snap_replication_policy: same as the one in `create`
            method.
        :param daily_snap_replication_policy: same as the one in `create`
            method.
        :param src_spa_interface: same as the one in `create` method.
        :param src_spb_interface: same as the one in `create` method.
        :param dst_spa_interface: same as the one in `create` method.
        :param dst_spb_interface: same as the one in `create` method.
        """
        req_body = self._cli.make_body(
            maxTimeOutOfSync=max_timeout_of_sync, name=name,
            hourlySnapReplicationPolicy=hourly_snap_replication_policy,
            dailySnapReplicationPolicy=daily_snap_replication_policy,
            srcSPAInterface=src_spa_interface,
            srcSPBInterface=src_spb_interface,
            dstSPAInterface=dst_spa_interface,
            dstSPBInterface=dst_spb_interface)

        resp = self.action('modify', **req_body)
        resp.raise_if_err()
        return resp

    def resume(self, force_full_copy=None,
               src_spa_interface=None, src_spb_interface=None,
               dst_spa_interface=None, dst_spb_interface=None):
        """
        Resumes a replication session.

        This can be applied on replication session when it's operational status
        is reported as Failed over, or Paused.

        :param force_full_copy: needed when replication session goes out of
            sync due to a fault.
            True - replicate all data.
            False - replicate changed data only.
        :param src_spa_interface: same as the one in `create` method.
        :param src_spb_interface: same as the one in `create` method.
        :param dst_spa_interface: same as the one in `create` method.
        :param dst_spb_interface: same as the one in `create` method.
        """
        req_body = self._cli.make_body(forceFullCopy=force_full_copy,
                                       srcSPAInterface=src_spa_interface,
                                       srcSPBInterface=src_spb_interface,
                                       dstSPAInterface=dst_spa_interface,
                                       dstSPBInterface=dst_spb_interface)

        resp = self.action('resume', **req_body)
        resp.raise_if_err()
        return resp

    def pause(self):
        """
        Pauses a replication session.

        This can be applied on replication session when in `OK` state.
        """
        resp = self.action('resume')
        resp.raise_if_err()
        return resp

    def sync(self):
        """
        Syncs a replication session.

        This can be applied to initiate a sync on demand independent of type of
        replication session - auto or manual sync.
        """
        resp = self.action('resume')
        resp.raise_if_err()
        return resp

    def failover(self, sync=None, force=None):
        """
        Fails over a replication session.

        :param sync: True - sync the source and destination resources before
            failing over the asynchronous replication session or keep them in
            sync after failing over the synchronous replication session.
            False - don't sync.
        :param force: True - skip pre-checks on file system(s) replication
            sessions of a NAS server when a replication failover is issued from
            the source NAS server.
            False - don't skip pre-checks.
        """
        req_body = self._cli.make_body(sync=sync, force=force)
        resp = self.action('failover', **req_body)
        resp.raise_if_err()
        return resp

    def failback(self, force_full_copy=None):
        """
        Fails back a replication session.

        This can be applied on a replication session that is failed over. Fail
        back will synchronize the changes done to original destination back to
        original source site and will restore the original direction of
        session.

        :param force_full_copy: indicates whether to sync back all data from
            the destination SP to the source SP during the failback session.
            True - Sync back all data.
            False - Sync back changed data only.
        """
        req_body = self._cli.make_body(forFullCopy=force_full_copy)
        resp = self.action('failback', **req_body)
        resp.raise_if_err()
        return resp


class UnityReplicationSessionList(UnityResourceList):
    @classmethod
    def get_resource_class(cls):
        return UnityReplicationSession
