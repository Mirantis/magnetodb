# Copyright 2013 Mirantis Inc.
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

import unittest
import uuid

from cassandra import cluster
from cassandra import decoder

from magnetodb.storage import models
from magnetodb.storage.impl import cassandra_impl as impl


TEST_CONNECTION = {'contact_points': ("localhost",)}


class FakeContext(object):
    def __init__(self, tenant):
        self.tenant = tenant


class TestCassandraBase(unittest.TestCase):
    KEYSPACE_PER_TEST_METHOD = "test"
    KEYSPACE_PER_TEST_CLASS = "class"

    _keyspace_scope = KEYSPACE_PER_TEST_CLASS

    test_data_keys = [
        ('id', 'decimal', '1', 1),
        ('range', 'text', "'1'", '1'),
    ]

    test_data_predefined_fields = [
        ('indexed', 'text', "'ind'", 'ind'),
        ('str', 'text', "'str'", 'str'),
        ('numbr', 'decimal', '1', 1),
        ('blb', 'blob', '0x{}'.format('blob'.encode('hex')), 'blob'),
        ('set_number', 'set<decimal>', '{1,2,3}', {1, 2, 3}),
        ('set_string', 'set<text>', "{'a','b','c'}", {'a', 'b', 'c'}),
        ('set_blob', 'set<blob>', '{{0x{}, 0x{}}}'.format(
            'blob1'.encode('hex'),
            'blob2'.encode('hex')), {'blob1', 'blob2'})
    ]

    test_data_system_fields = [
        ('system_hash', 'decimal'),
        ('system_attrs', 'map<text,blob>'),
        ('system_attr_types', 'map<text,text>'),
        ('system_attr_exist', 'set<text>'),
    ]

    test_data_dynamic_fields = [
        ('fnum', 'decimal', '1', 1),
        ('fstr', 'text', '"fstr"', 'fstr'),
        ('fblb', 'blob', '"fblob"', 'fblob'),
        ('fsnum', 'set<decimal>', '[1,2,3]', {1, 2, 3}),
        ('fsstr', 'set<text>', '["fa","fb","fc"]', {'fa', 'fb', 'fc'}),
        ('fsblob', 'set<blob>', '["fblob1", "fblob2"]', {'fblob1', 'fblob2'})
    ]

    C2S_TYPES = impl.CassandraStorageImpl.CASSANDRA_TO_STORAGE_TYPES

    @classmethod
    def setUpClass(cls):
        super(TestCassandraBase, cls).setUpClass()

        cls.CASANDRA_STORAGE_IMPL = impl.CassandraStorageImpl(
            **TEST_CONNECTION)

        cls.CLUSTER = cluster.Cluster(**TEST_CONNECTION)
        cls.SESSION = cls.CLUSTER.connect()
        cls.SESSION.row_factory = decoder.dict_factory

        if cls._keyspace_scope == cls.KEYSPACE_PER_TEST_CLASS:
            cls.keyspace = cls._get_unique_name()
            cls._create_keyspace(cls.keyspace)

        cls.expected_data = {
            name: models.AttributeValue(cls.C2S_TYPES[typ], val)
            for name, typ, _, val
            in (cls.test_data_keys +
                cls.test_data_dynamic_fields +
                cls.test_data_predefined_fields)}

    @classmethod
    def tearDownClass(cls):
        super(TestCassandraBase, cls).tearDownClass()
        if cls._keyspace_scope == cls.KEYSPACE_PER_TEST_CLASS:
            cls._drop_keyspace(cls.keyspace)

    def setUp(self):
        if self._keyspace_scope == self.KEYSPACE_PER_TEST_METHOD:
            self.keyspace = self._get_unique_name()
            self._create_keyspace(self.keyspace)

        self.context = FakeContext(self.keyspace)

        self.table_name = self._get_unique_name()

    def tearDown(self):
        if self._keyspace_scope == self.KEYSPACE_PER_TEST_METHOD:
            self._drop_keyspace(self.keyspace)

    @staticmethod
    def _get_unique_name():
        name = str(uuid.uuid4())
        return 'test' + filter(lambda x: x != '-', name)[:28]

    @classmethod
    def _create_keyspace(cls, keyspace):
        query = "CREATE KEYSPACE {} WITH replication".format(keyspace)
        query += " = {'class':'SimpleStrategy', 'replication_factor':1}"

        cls.SESSION.execute(query)

    @classmethod
    def _drop_keyspace(cls, keyspace):
        query = ("DROP KEYSPACE {}".format(keyspace))

        cls.SESSION.execute(query)

    def _get_table_names(self, keyspace=None):
        keyspace = keyspace or self.keyspace

        ks = self.CLUSTER.metadata.keyspaces[keyspace]

        return ks.tables.keys()

    def _create_table(self, keyspace=None, table_name=None):
        keyspace = keyspace or self.keyspace
        table_name = table_name or self.table_name
        query = "CREATE TABLE {}.{} (".format(keyspace, table_name)

        for field in self.test_data_keys:
            name, typ, _, _ = field
            query += 'user_{} {},'.format(name, typ)

        for field in self.test_data_predefined_fields:
            name, typ, _, _ = field
            query += 'user_{} {},'.format(name, typ)

        for field in self.test_data_system_fields:
            name, typ = field
            query += '{} {},'.format(name, typ)

        query += " PRIMARY KEY(user_id, user_range))"

        self.SESSION.execute(query)
        self._create_index(attr='system_hash')

    def _create_index(self, keyspace=None, table_name=None,
                      attr='user_indexed', index_name=""):
        keyspace = keyspace or self.keyspace
        table_name = table_name or self.table_name

        if index_name:
            index_name = "_".join((table_name, index_name))

        query = "CREATE INDEX {} ON {}.{} ({})".format(
            index_name, keyspace, table_name, attr)
        self.SESSION.execute(query)

    def _drop_table(self, keyspace=None, table_name=None):
        keyspace = keyspace or self.keyspace
        table_name = None or self.table_name
        query = "DROP TABLE IF EXISTS {}.{}".format(keyspace, table_name)
        self.SESSION.execute(query)

    def _select_all(self, keyspace=None, table_name=None):
        keyspace = keyspace or self.keyspace
        table_name = table_name or self.table_name
        query = "SELECT * FROM {}.{}".format(keyspace, table_name)
        return self.SESSION.execute(query)

    def _insert_data(self, range_value=1):
        query = "UPDATE {}.{} SET ".format(self.keyspace, self.table_name)

        for field in self.test_data_predefined_fields:
            name, typ, sval, _ = field
            query += 'user_{}={},'.format(name, sval)

        for field in self.test_data_dynamic_fields:
            name, typ, sval, _ = field
            query += "system_attrs['{}'] = 0x{},".format(
                name, str(sval).encode('hex'))

        for field in (self.test_data_keys +
                      self.test_data_dynamic_fields +
                      self.test_data_predefined_fields):
            name, typ, _, _ = field
            query += "system_attr_types['{}'] ='{}',".format(name, typ)
            query += ("system_attr_exist = system_attr_exist + {{'{}'}},"
                      .format(name))

        query += 'system_hash = 1'

        query += " WHERE user_id = 1 AND user_range='{}'".format(range_value)

        self.SESSION.execute(query)

    def _validate_data(self, data):

        self.assertDictEqual(self.expected_data, data)


class TestCassandraTableCrud(TestCassandraBase):

    def test_create_table(self):
        self.assertEqual([], self._get_table_names())

        attrs = {models.AttributeDefinition(name, self.C2S_TYPES[typ])
                 for name, typ, _, _
                 in (self.test_data_keys +
                     self.test_data_predefined_fields)}

        index_defs = {
            models.IndexDefinition('index_name', 'indexed')
        }

        schema = models.TableSchema(self.table_name, attrs, ['id', 'range'],
                                    index_defs)

        self.CASANDRA_STORAGE_IMPL.create_table(self.context, schema)

        self.assertEqual([self.table_name], self._get_table_names())

    def test_list_table(self):
        self.assertNotIn(self.table_name,
                         self.CASANDRA_STORAGE_IMPL.list_tables(self.context))

        self._create_table()

        self.assertIn(self.table_name,
                      self.CASANDRA_STORAGE_IMPL.list_tables(self.context))

    def test_describe_table(self):

        self._create_table()
        self._create_index(index_name="index_name")

        attrs = {models.AttributeDefinition(name, self.C2S_TYPES[typ])
                 for name, typ, _, _
                 in (self.test_data_keys +
                     self.test_data_predefined_fields)}

        index_defs = {
            models.IndexDefinition('index_name', 'indexed')
        }

        schema = models.TableSchema(self.table_name, attrs, ['id', 'range'],
                                    index_defs)

        desc = self.CASANDRA_STORAGE_IMPL.describe_table(
            self.context, self.table_name)

        self.assertEqual(schema, desc)

    def test_delete_table(self):
        self._create_table()

        self.assertIn(self.table_name, self._get_table_names())

        self.CASANDRA_STORAGE_IMPL.delete_table(self.context, self.table_name)

        self.assertNotIn(self.table_name, self._get_table_names())


class TestCassandraDeleteItem(TestCassandraBase):

    def test_delete_item_where(self):
        self._create_table()
        self._create_index()
        self._insert_data()
        self._insert_data(2)

        del_req = models.DeleteItemRequest(
            self.table_name,
            {'id': models.Condition.eq(1), 'range': models.Condition.eq('1')})

        self.CASANDRA_STORAGE_IMPL.delete_item(
            self.context, del_req)

        all = self._select_all()

        self.assertEqual(1, len(all))
        self.assertEqual('2', all[0]['user_range'])

    def test_delete_item_where_negative(self):
        self._create_table()
        self._create_index()
        self._insert_data()

        del_req = models.DeleteItemRequest(
            self.table_name,
            {'id': models.Condition.eq(1), 'range': models.Condition.eq('2')})

        self.CASANDRA_STORAGE_IMPL.delete_item(
            self.context, del_req)

        all = self._select_all()

        self.assertEqual(1, len(all))
        self.assertEqual(1, all[0]['user_id'])

    @unittest.skip("conditional updates noy yet implemented")
    def test_delete_item_if_exists(self):
        self._create_table()
        self._create_index()

        query = ("INSERT INTO {}.{} (user_id, user_range,"
                 " user_str, user_indexed)"
                 " VALUES (1, '1', '1', '1')").format(self.keyspace,
                                                      self.table_name)

        self.SESSION.execute(query)

        all = self._select_all()

        self.assertEqual(1, len(all))
        self.assertEqual(1, all[0].user_id)

        expected = {'str': models.ExpectedCondition.exists()}

        del_req = models.DeleteItemRequest(
            self.table_name,
            {'id': models.Condition.eq(1), 'range': models.Condition.eq('1')})

        self.CASANDRA_STORAGE_IMPL.delete_item(
            self.context, del_req, expected)

        all = self._select_all()

        self.assertEqual(0, len(all))

    @unittest.skip("conditional updates noy yet implemented")
    def test_delete_item_if_exists_negative(self):
        self._create_table()
        self._create_index()

        query = ("INSERT INTO {}.{} (user_id, user_range,"
                 " user_str, user_indexed)"
                 " VALUES (1, '1', null, '1')").format(self.keyspace,
                                                       self.table_name)

        self.SESSION.execute(query)

        all = self._select_all()

        self.assertEqual(1, len(all))
        self.assertEqual(1, all[0].user_id)

        expected = {'str': models.ExpectedCondition.exists()}

        del_req = models.DeleteItemRequest(
            self.table_name,
            {'id': models.Condition.eq(1), 'range': models.Condition.eq('1')})

        self.CASANDRA_STORAGE_IMPL.delete_item(
            self.context, del_req, expected)

        all = self._select_all()

        self.assertEqual(1, len(all))
        self.assertEqual(1, all[0].user_id)

    @unittest.skip("conditional updates noy yet implemented")
    def test_delete_item_if_not_exists(self):
        self._create_table()
        self._create_index()

        query = ("INSERT INTO {}.{} (user_id, user_range,"
                 " user_str, user_indexed)"
                 " VALUES (1, '1', null, '1')").format(self.keyspace,
                                                       self.table_name)

        self.SESSION.execute(query)

        all = self._select_all()

        self.assertEqual(1, len(all))
        self.assertEqual(1, all[0].user_id)

        expected = {'str': models.ExpectedCondition.not_exists()}

        del_req = models.DeleteItemRequest(
            self.table_name,
            {'id': models.Condition.eq(1), 'range': models.Condition.eq('1')})

        self.CASANDRA_STORAGE_IMPL.delete_item(
            self.context, del_req, expected)

        all = self._select_all()

        self.assertEqual(0, len(all))

    @unittest.skip("conditional updates noy yet implemented")
    def test_delete_item_if_not_exists_negative(self):
        self._create_table()
        self._create_index()

        query = ("INSERT INTO {}.{} (user_id, user_range,"
                 " user_str, user_indexed)"
                 " VALUES (1, '1', '1', '1')").format(self.keyspace,
                                                      self.table_name)

        self.SESSION.execute(query)

        all = self._select_all()

        self.assertEqual(1, len(all))
        self.assertEqual(1, all[0].user_id)

        expected = {'str': models.ExpectedCondition.not_exists()}

        del_req = models.DeleteItemRequest(
            self.table_name,
            {'id': models.Condition.eq(1), 'range': models.Condition.eq('1')})

        self.CASANDRA_STORAGE_IMPL.delete_item(
            self.context, del_req, expected)

        all = self._select_all()

        self.assertEqual(1, len(all))
        self.assertEqual(1, all[0].user_id)


class TestCassandraSelectItem(TestCassandraBase):

    def test_select_item(self):
        self._create_table()
        self._create_index()

        self._insert_data()

        indexed_cond = {'id': models.Condition.eq(1),
                        'range': models.Condition.eq('1')}

        result = self.CASANDRA_STORAGE_IMPL.select_item(
            self.context, self.table_name, indexed_cond)

        self.assertEqual(1, len(result))
        self._validate_data(result[0])

    def test_select_item_attr(self):
        self._create_table()
        self._create_index()

        self._insert_data()

        indexed_cond = {'id': models.Condition.eq(1),
                        'range': models.Condition.eq('1')}

        result = self.CASANDRA_STORAGE_IMPL.select_item(
            self.context, self.table_name, indexed_cond, ['fstr'])

        self.assertEqual(1, len(result))
        self.assertEqual(
            {'fstr': models.AttributeValue(
                models.ATTRIBUTE_TYPE_STRING, 'fstr')},
            result[0])

    def test_select_item_negative(self):
        self._create_table()
        self._create_index()

        self._insert_data()

        indexed_cond = {'id': models.Condition.eq(1),
                        'range': models.Condition.eq('2')}

        result = self.CASANDRA_STORAGE_IMPL.select_item(
            self.context, self.table_name, indexed_cond)

        self.assertEqual(0, len(result))

    def test_select_item_less(self):
        self._create_table()
        self._create_index()

        self._insert_data()

        indexed_cond = {'id': models.Condition.eq(1),
                        'range': models.IndexedCondition.lt('2')}

        result = self.CASANDRA_STORAGE_IMPL.select_item(
            self.context, self.table_name, indexed_cond)

        self.assertEqual(1, len(result))
        self._validate_data(result[0])

    def test_select_item_less_negative(self):
        self._create_table()
        self._create_index()

        self._insert_data()

        indexed_cond = {'id': models.Condition.eq(1),
                        'range': models.IndexedCondition.lt('1')}

        result = self.CASANDRA_STORAGE_IMPL.select_item(
            self.context, self.table_name, indexed_cond)

        self.assertEqual(0, len(result))

    def test_select_item_less_eq(self):
        self._create_table()
        self._create_index()

        self._insert_data()

        indexed_cond = {'id': models.Condition.eq(1),
                        'range': models.IndexedCondition.le('1')}

        result = self.CASANDRA_STORAGE_IMPL.select_item(
            self.context, self.table_name, indexed_cond)

        self.assertEqual(1, len(result))
        self._validate_data(result[0])

    def test_select_item_less_eq_negative(self):
        self._create_table()
        self._create_index()

        self._insert_data()

        indexed_cond = {'id': models.Condition.eq(1),
                        'range': models.IndexedCondition.le('0')}

        result = self.CASANDRA_STORAGE_IMPL.select_item(
            self.context, self.table_name, indexed_cond)

        self.assertEqual(0, len(result))

    def test_select_item_greater(self):
        self._create_table()
        self._create_index()

        self._insert_data()

        indexed_cond = {'id': models.Condition.eq(1),
                        'range': models.IndexedCondition.gt('0')}

        result = self.CASANDRA_STORAGE_IMPL.select_item(
            self.context, self.table_name, indexed_cond)

        self.assertEqual(1, len(result))
        self._validate_data(result[0])

    def test_select_item_greater_negative(self):
        self._create_table()
        self._create_index()

        self._insert_data()

        indexed_cond = {'id': models.Condition.eq(1),
                        'range': models.IndexedCondition.gt('1')}

        result = self.CASANDRA_STORAGE_IMPL.select_item(
            self.context, self.table_name, indexed_cond)

        self.assertEqual(0, len(result))

    def test_select_item_greater_eq(self):
        self._create_table()
        self._create_index()

        self._insert_data()

        indexed_cond = {'id': models.Condition.eq(1),
                        'range': models.IndexedCondition.ge('1')}

        result = self.CASANDRA_STORAGE_IMPL.select_item(
            self.context, self.table_name, indexed_cond)

        self.assertEqual(1, len(result))
        self._validate_data(result[0])

    def test_select_item_greater_eq_negative(self):
        self._create_table()
        self._create_index()

        self._insert_data()

        indexed_cond = {'id': models.Condition.eq(1),
                        'range': models.IndexedCondition.ge('2')}

        result = self.CASANDRA_STORAGE_IMPL.select_item(
            self.context, self.table_name, indexed_cond)

        self.assertEqual(0, len(result))

    def test_select_item_indexed(self):
        self._create_table()
        self._create_index()

        self._insert_data()

        indexed_cond = {'id': models.Condition.eq(1),
                        'range': models.Condition.eq('1'),
                        'indexed': models.IndexedCondition.le('ind')}

        result = self.CASANDRA_STORAGE_IMPL.select_item(
            self.context, self.table_name, indexed_cond)

        self.assertEqual(1, len(result))
        self._validate_data(result[0])

    def test_select_item_indexed_negative(self):
        self._create_table()
        self._create_index()

        self._insert_data()

        indexed_cond = {'id': models.Condition.eq(1),
                        'range': models.Condition.eq('1'),
                        'indexed': models.IndexedCondition.lt('ind')}

        result = self.CASANDRA_STORAGE_IMPL.select_item(
            self.context, self.table_name, indexed_cond)

        self.assertEqual(0, len(result))

    def test_select_with_limit(self):
        self._create_table()
        self._create_index()
        self._insert_data()
        self._insert_data(2)

        indexed_cond = {'id': models.Condition.eq(1),
                        'range': models.IndexedCondition.ge('1')}

        result = self.CASANDRA_STORAGE_IMPL.select_item(
            self.context, self.table_name, indexed_cond)

        self.assertEqual(2, len(result))

        result = self.CASANDRA_STORAGE_IMPL.select_item(
            self.context, self.table_name, indexed_cond, limit=1)

        self.assertEqual(1, len(result))


class TestCassandraUpdateItem(TestCassandraBase):
    def test_update_item_put_str(self):
        self._create_table()
        self._create_index()
        self._insert_data()

        keys = {'id': models.Condition.eq(1),
                'range': models.Condition.eq('1')}

        actions = {
            'str': models.UpdateItemAction(
                models.UpdateItemAction.UPDATE_ACTION_PUT,
                models.AttributeValue(models.ATTRIBUTE_TYPE_STRING, 'new')),
        }

        self.CASANDRA_STORAGE_IMPL.update_item(
            self.context, self.table_name, keys, actions)

        expected = {name: models.AttributeValue(self.C2S_TYPES[typ], val)
                    for name, typ, _, val
                    in (self.test_data_keys +
                        self.test_data_predefined_fields +
                        self.test_data_dynamic_fields)}

        expected['str'] = models.AttributeValue(
            models.ATTRIBUTE_TYPE_STRING, 'new')

        result = self.CASANDRA_STORAGE_IMPL.select_item(
            self.context, self.table_name, keys)

        self.assertEquals([expected], result)

    def test_update_item_put_number(self):
        self._create_table()
        self._create_index()
        self._insert_data()

        keys = {'id': models.Condition.eq(1),
                'range': models.Condition.eq('1')}

        actions = {
            'numbr': models.UpdateItemAction(
                models.UpdateItemAction.UPDATE_ACTION_PUT,
                models.AttributeValue(models.ATTRIBUTE_TYPE_NUMBER, 42)),
        }

        self.CASANDRA_STORAGE_IMPL.update_item(
            self.context, self.table_name, keys, actions)

        expected = {name: models.AttributeValue(self.C2S_TYPES[typ], val)
                    for name, typ, _, val
                    in (self.test_data_keys +
                        self.test_data_predefined_fields +
                        self.test_data_dynamic_fields)}

        expected['numbr'] = models.AttributeValue(
            models.ATTRIBUTE_TYPE_NUMBER, 42)

        result = self.CASANDRA_STORAGE_IMPL.select_item(
            self.context, self.table_name, keys)

        self.assertEquals([expected], result)

    def test_update_item_put_blob(self):
        self._create_table()
        self._create_index()
        self._insert_data()

        keys = {'id': models.Condition.eq(1),
                'range': models.Condition.eq('1')}

        actions = {
            'blb': models.UpdateItemAction(
                models.UpdateItemAction.UPDATE_ACTION_PUT,
                models.AttributeValue(models.ATTRIBUTE_TYPE_BLOB, 'new')),
        }

        self.CASANDRA_STORAGE_IMPL.update_item(
            self.context, self.table_name, keys, actions)

        expected = {name: models.AttributeValue(self.C2S_TYPES[typ], val)
                    for name, typ, _, val
                    in (self.test_data_keys +
                        self.test_data_predefined_fields +
                        self.test_data_dynamic_fields)}

        expected['blb'] = models.AttributeValue(
            models.ATTRIBUTE_TYPE_BLOB, 'new')

        result = self.CASANDRA_STORAGE_IMPL.select_item(
            self.context, self.table_name, keys)

        self.assertEquals([expected], result)

    def test_update_item_put_set_str(self):
        self._create_table()
        self._create_index()
        self._insert_data()

        keys = {'id': models.Condition.eq(1),
                'range': models.Condition.eq('1')}

        actions = {
            'set_string': models.UpdateItemAction(
                models.UpdateItemAction.UPDATE_ACTION_PUT,
                models.AttributeValue(
                    models.ATTRIBUTE_TYPE_STRING_SET, {'new'})),
        }

        self.CASANDRA_STORAGE_IMPL.update_item(
            self.context, self.table_name, keys, actions)

        expected = {name: models.AttributeValue(self.C2S_TYPES[typ], val)
                    for name, typ, _, val
                    in (self.test_data_keys +
                        self.test_data_predefined_fields +
                        self.test_data_dynamic_fields)}

        expected['set_string'] = models.AttributeValue(
            models.ATTRIBUTE_TYPE_STRING_SET, {'new'})

        result = self.CASANDRA_STORAGE_IMPL.select_item(
            self.context, self.table_name, keys)

        self.assertEquals([expected], result)

    def test_update_item_put_set_number(self):
        self._create_table()
        self._create_index()
        self._insert_data()

        keys = {'id': models.Condition.eq(1),
                'range': models.Condition.eq('1')}

        actions = {
            'set_number': models.UpdateItemAction(
                models.UpdateItemAction.UPDATE_ACTION_PUT,
                models.AttributeValue(models.ATTRIBUTE_TYPE_NUMBER_SET, {42})),
        }

        self.CASANDRA_STORAGE_IMPL.update_item(
            self.context, self.table_name, keys, actions)

        expected = {name: models.AttributeValue(self.C2S_TYPES[typ], val)
                    for name, typ, _, val
                    in (self.test_data_keys +
                        self.test_data_predefined_fields +
                        self.test_data_dynamic_fields)}

        expected['set_number'] = models.AttributeValue(
            models.ATTRIBUTE_TYPE_NUMBER_SET, {42})

        result = self.CASANDRA_STORAGE_IMPL.select_item(
            self.context, self.table_name, keys)

        self.assertEquals([expected], result)

    def test_update_item_put_set_blob(self):
        self._create_table()
        self._create_index()
        self._insert_data()

        keys = {'id': models.Condition.eq(1),
                'range': models.Condition.eq('1')}

        actions = {
            'set_blob': models.UpdateItemAction(
                models.UpdateItemAction.UPDATE_ACTION_PUT,
                models.AttributeValue(
                    models.ATTRIBUTE_TYPE_BLOB_SET, {'new'})),
        }

        self.CASANDRA_STORAGE_IMPL.update_item(
            self.context, self.table_name, keys, actions)

        expected = {name: models.AttributeValue(self.C2S_TYPES[typ], val)
                    for name, typ, _, val
                    in (self.test_data_keys +
                        self.test_data_predefined_fields +
                        self.test_data_dynamic_fields)}

        expected['set_blob'] = models.AttributeValue(
            models.ATTRIBUTE_TYPE_BLOB_SET, {'new'})

        result = self.CASANDRA_STORAGE_IMPL.select_item(
            self.context, self.table_name, keys)

        self.assertEquals([expected], result)

    def test_update_item_put_dynamic_str(self):
        self._create_table()
        self._create_index()
        self._insert_data()

        keys = {'id': models.Condition.eq(1),
                'range': models.Condition.eq('1')}

        actions = {
            'fstr': models.UpdateItemAction(
                models.UpdateItemAction.UPDATE_ACTION_PUT,
                models.AttributeValue(models.ATTRIBUTE_TYPE_STRING, 'new')),
        }

        self.CASANDRA_STORAGE_IMPL.update_item(
            self.context, self.table_name, keys, actions)

        expected = {name: models.AttributeValue(self.C2S_TYPES[typ], val)
                    for name, typ, _, val
                    in (self.test_data_keys +
                        self.test_data_predefined_fields +
                        self.test_data_dynamic_fields)}

        expected['fstr'] = models.AttributeValue(
            models.ATTRIBUTE_TYPE_STRING, 'new')

        result = self.CASANDRA_STORAGE_IMPL.select_item(
            self.context, self.table_name, keys)

        self.assertEquals([expected], result)

    def test_update_item_put_dynamic_number(self):
        self._create_table()
        self._create_index()
        self._insert_data()

        keys = {'id': models.Condition.eq(1),
                'range': models.Condition.eq('1')}

        actions = {
            'fnum': models.UpdateItemAction(
                models.UpdateItemAction.UPDATE_ACTION_PUT,
                models.AttributeValue(models.ATTRIBUTE_TYPE_NUMBER, 42)),
        }

        self.CASANDRA_STORAGE_IMPL.update_item(
            self.context, self.table_name, keys, actions)

        expected = {name: models.AttributeValue(self.C2S_TYPES[typ], val)
                    for name, typ, _, val
                    in (self.test_data_keys +
                        self.test_data_predefined_fields +
                        self.test_data_dynamic_fields)}

        expected['fnum'] = models.AttributeValue(
            models.ATTRIBUTE_TYPE_NUMBER, 42)

        result = self.CASANDRA_STORAGE_IMPL.select_item(
            self.context, self.table_name, keys)

        self.assertEquals([expected], result)

    def test_update_item_put_dynamic_blob(self):
        self._create_table()
        self._create_index()
        self._insert_data()

        keys = {'id': models.Condition.eq(1),
                'range': models.Condition.eq('1')}

        actions = {
            'fblb': models.UpdateItemAction(
                models.UpdateItemAction.UPDATE_ACTION_PUT,
                models.AttributeValue(models.ATTRIBUTE_TYPE_BLOB, 'new')),
        }

        self.CASANDRA_STORAGE_IMPL.update_item(
            self.context, self.table_name, keys, actions)

        expected = {name: models.AttributeValue(self.C2S_TYPES[typ], val)
                    for name, typ, _, val
                    in (self.test_data_keys +
                        self.test_data_predefined_fields +
                        self.test_data_dynamic_fields)}

        expected['fblb'] = models.AttributeValue(
            models.ATTRIBUTE_TYPE_BLOB, 'new')

        result = self.CASANDRA_STORAGE_IMPL.select_item(
            self.context, self.table_name, keys)

        self.assertEquals([expected], result)

    def test_update_item_put_dynamic_set_str(self):
        self._create_table()
        self._create_index()
        self._insert_data()

        keys = {'id': models.Condition.eq(1),
                'range': models.Condition.eq('1')}

        actions = {
            'fsstr': models.UpdateItemAction(
                models.UpdateItemAction.UPDATE_ACTION_PUT,
                models.AttributeValue(
                    models.ATTRIBUTE_TYPE_STRING_SET, {'new1', 'new2'})),
        }

        self.CASANDRA_STORAGE_IMPL.update_item(
            self.context, self.table_name, keys, actions)

        expected = {name: models.AttributeValue(self.C2S_TYPES[typ], val)
                    for name, typ, _, val
                    in (self.test_data_keys +
                        self.test_data_predefined_fields +
                        self.test_data_dynamic_fields)}

        expected['fsstr'] = models.AttributeValue(
            models.ATTRIBUTE_TYPE_STRING_SET, {'new1', 'new2'})

        result = self.CASANDRA_STORAGE_IMPL.select_item(
            self.context, self.table_name, keys)

        self.assertEquals([expected], result)

    def test_update_item_put_dynamic_set_number(self):
        self._create_table()
        self._create_index()
        self._insert_data()

        keys = {'id': models.Condition.eq(1),
                'range': models.Condition.eq('1')}

        actions = {
            'fsnum': models.UpdateItemAction(
                models.UpdateItemAction.UPDATE_ACTION_PUT,
                models.AttributeValue(
                    models.ATTRIBUTE_TYPE_NUMBER_SET, {42, 43})),
        }

        self.CASANDRA_STORAGE_IMPL.update_item(
            self.context, self.table_name, keys, actions)

        expected = {name: models.AttributeValue(self.C2S_TYPES[typ], val)
                    for name, typ, _, val
                    in (self.test_data_keys +
                        self.test_data_predefined_fields +
                        self.test_data_dynamic_fields)}

        expected['fsnum'] = models.AttributeValue(
            models.ATTRIBUTE_TYPE_NUMBER_SET, {42, 43})

        result = self.CASANDRA_STORAGE_IMPL.select_item(
            self.context, self.table_name, keys)

        self.assertEquals([expected], result)

    def test_update_item_put_dynamic_set_blob(self):
        self._create_table()
        self._create_index()
        self._insert_data()

        keys = {'id': models.Condition.eq(1),
                'range': models.Condition.eq('1')}

        actions = {
            'fsblb': models.UpdateItemAction(
                models.UpdateItemAction.UPDATE_ACTION_PUT,
                models.AttributeValue(
                    models.ATTRIBUTE_TYPE_BLOB_SET, {'new1', 'new2'})),
        }

        self.CASANDRA_STORAGE_IMPL.update_item(
            self.context, self.table_name, keys, actions)

        expected = {name: models.AttributeValue(self.C2S_TYPES[typ], val)
                    for name, typ, _, val
                    in (self.test_data_keys +
                        self.test_data_predefined_fields +
                        self.test_data_dynamic_fields)}

        expected['fsblb'] = models.AttributeValue(
            models.ATTRIBUTE_TYPE_BLOB_SET, {'new1', 'new2'})

        result = self.CASANDRA_STORAGE_IMPL.select_item(
            self.context, self.table_name, keys)

        self.assertEquals([expected], result)

    def test_update_item_delete(self):
        self._create_table()
        self._create_index()
        self._insert_data()

        keys = {'id': models.Condition.eq(1),
                'range': models.Condition.eq('1')}

        actions = {
            'str': models.UpdateItemAction(
                models.UpdateItemAction.UPDATE_ACTION_DELETE, None),
            'fstr': models.UpdateItemAction(
                models.UpdateItemAction.UPDATE_ACTION_DELETE, None)
        }

        self.CASANDRA_STORAGE_IMPL.update_item(
            self.context, self.table_name, keys, actions)

        expected = {name: models.AttributeValue(self.C2S_TYPES[typ], val)
                    for name, typ, _, val
                    in (self.test_data_keys +
                        self.test_data_predefined_fields +
                        self.test_data_dynamic_fields)}

        del expected['str']
        del expected['fstr']

        result = self.CASANDRA_STORAGE_IMPL.select_item(
            self.context, self.table_name, keys)

        self.assertEquals([expected], result)
