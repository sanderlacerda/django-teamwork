import logging
import time

from django.conf import settings
from django.contrib.auth.models import AnonymousUser, User, Permission, Group
from django.contrib.contenttypes.models import ContentType

from django.test import TestCase

from nose.tools import assert_equal, with_setup, assert_false, eq_, ok_
from nose.plugins.attrib import attr

from teamwork_example.wiki.models import Document

from ..models import Team, Role, Policy
from ..backends import TeamworkBackend

from . import TestCaseBase


class TeamBackendTests(TestCaseBase):

    def setUp(self):
        super(TeamBackendTests, self).setUp()

        self.backend = TeamworkBackend()

    def test_empty_object(self):
        """Backend should yield empty permission set when no object supplied"""
        eq_(set(), self.backend.get_all_permissions(self.users['randomguy1']))

    def test_superuser_is_super(self):
        """A superuser should be granted all object permissions"""
        doc = Document.objects.create(name='random_doc_1',
                                      creator=self.users['randomguy1'])
        obj_perms = Permission.objects.filter(content_type=self.doc_ct).all()
        expected_perms = set([u"%s.%s" % (self.doc_ct.app_label, p.codename)
                              for p in obj_perms])
        result_perms = self.users['admin'].get_all_permissions(doc)
        eq_(expected_perms, result_perms)
        for perm in expected_perms:
            self.users['admin'].has_perm(perm)

    def test_mixed_permissions(self):
        """Policies & teams grant permissions by object to users & groups"""
        anon_user = AnonymousUser()
        founder_user = User.objects.create_user(
            'founder0', 'founder0@example.com', 'founder0')
        auth_user = self.users['randomguy1']
        role_user = self.users['randomguy2']
        users_users = [self.users[u] for u in ('randomguy3', 'randomguy4')]
        group_users = [self.users[u] for u in ('randomguy5', 'randomguy6')]
        owner_user = self.users['randomguy7']

        expected_anon_perms = set((u'frob', u'xyzzy'))
        expected_auth_perms = set((u'xyzzy', u'hello'))
        expected_role_perms = set((u'frob', u'hello'))
        expected_users_perms = set((u'frob',))
        expected_group_perms = set((u'hello',))
        expected_owner_perms = set((u'add_document_child',))

        team = Team.objects.create(name='general_permissive_team',
                                   founder=founder_user)

        doc = Document.objects.create(name='general_doc_1',
                                      creator=owner_user,
                                      team=team)

        role1 = Role.objects.create(name='role1', team=team)
        role1.users.add(role_user)
        perms = self.names_to_doc_permissions(expected_role_perms)
        role1.permissions.add(*perms)

        anon_policy = Policy.objects.create(content_object=doc,
                                            anonymous=True)
        perms = self.names_to_doc_permissions(expected_anon_perms)
        anon_policy.permissions.add(*perms)

        auth_policy = Policy.objects.create(content_object=doc,
                                            authenticated=True)
        perms = self.names_to_doc_permissions(expected_auth_perms)
        auth_policy.permissions.add(*perms)

        users_policy = Policy.objects.create(content_object=doc)
        perms = self.names_to_doc_permissions(expected_users_perms)
        users_policy.users.add(*users_users)
        users_policy.permissions.add(*perms)

        group_policy = Policy.objects.create(content_object=doc)
        group = Group.objects.create(name='Honk honk')
        for user in group_users:
            user.groups.add(group)
        group_policy.groups.add(group)
        perms = self.names_to_doc_permissions(expected_group_perms)
        group_policy.permissions.add(*perms)

        owner_policy = Policy.objects.create(content_object=doc,
                                             apply_to_owners=True)
        perms = self.names_to_doc_permissions(expected_owner_perms)
        owner_policy.permissions.add(*perms)

        def assert_perms(expected_perms, user):
            eq_(expected_perms, set(
                n.split('.')[1] for n in
                user.get_all_permissions(doc)))
            for perm in expected_perms:
                user.has_perm(perm, doc)

        assert_perms(expected_anon_perms, anon_user)
        assert_perms(expected_auth_perms, auth_user)
        assert_perms(expected_role_perms, role_user)
        assert_perms(expected_auth_perms.union(expected_owner_perms),
                     owner_user)

        expected_perms = expected_users_perms.union(expected_auth_perms)
        for user in users_users:
            assert_perms(expected_perms, user)

        expected_perms = expected_group_perms.union(expected_auth_perms)
        for user in group_users:
            assert_perms(expected_perms, user)

    def test_object_logic_permissions(self):
        """Objects can apply custom logic to permissions"""
        u_quux1 = User.objects.create_user(
            'quux1', 'quux1@example.com', 'quux1')
        u_randomguy1 = User.objects.create_user(
            'randomguy23', 'randomguy23@example.com', 'randomguy23')
        doc = Document.objects.create(name='Quuxy')
        ok_(u_quux1.has_perm('wiki.quux', doc))
        ok_(not u_randomguy1.has_perm('wiki.quux', doc))

    def test_parent_permissions(self):
        """Content objects can supply a list of parents for inheritance"""
        user = User.objects.create_user('noob1', 'noob1@example.com', 'noob1')

        # Set up document tree:
        #  /- 1 - 4
        # 0 - 2 - 5
        #  \- 3 - 6
        #  \- 7 - 8
        docs = []
        for idx in range(0, 9):
            docs.append(Document.objects.create(name=('tree%s' % idx)))
        links = ((0, 1), (1, 4),
                 (0, 2), (2, 5),
                 (0, 3), (3, 6),
                 (0, 7), (7, 8))
        for (parent_idx, child_idx) in links:
            child = docs[child_idx]
            child.parent = docs[parent_idx]
            child.save()

        policy_on_0 = Policy.objects.create(content_object=docs[0],
                                            authenticated=True)
        perms = self.names_to_doc_permissions(('frob',))
        policy_on_0.permissions.add(*perms)

        policy_on_1 = Policy.objects.create(content_object=docs[1],
                                            authenticated=True)
        perms = self.names_to_doc_permissions(('xyzzy',))
        policy_on_1.permissions.add(*perms)

        policy_on_2 = Policy.objects.create(content_object=docs[2],
                                            authenticated=True)
        perms = self.names_to_doc_permissions(('hello',))
        policy_on_2.permissions.add(*perms)

        policy_on_5 = Policy.objects.create(content_object=docs[5],
                                            authenticated=True)
        perms = self.names_to_doc_permissions(('quux',))
        policy_on_5.permissions.add(*perms)

        # Set up a team & role to exercise team inheritance
        team_for_7 = Team.objects.create(name="Team for 7")
        docs[7].team = team_for_7
        docs[7].save()

        role1 = Role.objects.create(name='role1_for_7', team=team_for_7)
        role1.users.add(user)
        perms = self.names_to_doc_permissions(('add_document_child',))
        role1.permissions.add(*perms)

        # Check the team inheritance as a special case
        perms = user.get_all_permissions(docs[8])
        eq_(set(('wiki.add_document_child',)), perms)

        cases = (
            (u'wiki.frob',),   # 0 has own policy
            (u'wiki.xyzzy',),  # 1 has own policy
            (u'wiki.hello',),  # 2 has own policy
            (u'wiki.frob',),   # 3 inherits from 0
            (u'wiki.xyzzy',),  # 4 inherits from 1
            (u'wiki.quux',),   # 5 has own policy
            (u'wiki.frob',),   # 6 inherits from 0
        )
        for idx in range(0, len(cases)):
            doc = docs[idx]
            case = cases[idx]
            perms = user.get_all_permissions(doc)
            eq_(set(case), perms,
                'Permissions for doc #%s should be %s, were instead %s' %
                (idx, case, perms))
