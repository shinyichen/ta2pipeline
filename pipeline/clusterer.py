import numpy as np
import pandas as pd
import os
import io
from copy import deepcopy
import json
import csv
import sys
import random
import string
from collections import defaultdict
import glob
import warnings
from config import config, get_logger
from operator import itemgetter
import rltk


logger = get_logger('clusterer')


def flatten(list_, remove_none=True):
    # flatten([1,2,3,4, [2,2,4],[13,[2,3,2]]])
    if isinstance(list_, (list, tuple)):
        ret = []
        for l in list_:
            for n in flatten(l):
                ret.append(n)
        return ret
    else:
        if remove_none and not list_:
            return []
        return [list_]


def highest_score_indices(list_):
    # returns all indices have the same highest score
    sorted_indices = sorted(range(len(list_)), key=lambda i: list_[i], reverse=True)
    for i in range(1, len(sorted_indices)):
        if list_[sorted_indices[i - 1]] != list_[sorted_indices[i]]:
            return sorted_indices[:i]
    return sorted_indices


def select_most_overlapped(name, *targets):
    # selecting the most possible target depends on overlap, returns its index
    max_ = 0
    max_index = 0
    for idx, t in enumerate(targets):
        overlap = len(set(name) & set(t))
        if overlap > max_:
            max_ = overlap
            max_index = idx
    return max_index


@rltk.set_id('e')
class GaiaRecord(rltk.AutoGeneratedRecord):
    # Index(['Unnamed: 0', 'e', 'name', 'type', 'target', 'target_score',
    #        'target_type', 'target_name', 'fbid', 'fbid_score_avg',
    #        'fbid_score_max', 'wikidata', 'wikidata_label_en', 'wikidata_label_ru',
    #        'wikidata_label_uk', 'wikidata_description_en',
    #        'wikidata_description_ru', 'wikidata_description_uk',
    #        'wikidata_alias_en', 'wikidata_alias_ru', 'wikidata_alias_uk',
    #        'infojust_confidence', 'informative_justification', 'just_confidence',
    #        'justified_by', 'source'],

    @rltk.cached_property
    def selected_wikidata_index(self):
        if self.wikidata:
            selected_indices = highest_score_indices(self.fbid_score_avg)
            if len(selected_indices) == 1:
                return selected_indices[0]
            else:
                label_en = itemgetter(*selected_indices)(self.wikidata_label_en) # (str)
                label_ru = itemgetter(*selected_indices)(self.wikidata_label_ru)
                label_uk = itemgetter(*selected_indices)(self.wikidata_label_uk)
                alias_en = itemgetter(*selected_indices)(self.wikidata_alias_en) # (tuple)
                alias_ru = itemgetter(*selected_indices)(self.wikidata_alias_ru)
                alias_uk = itemgetter(*selected_indices)(self.wikidata_alias_uk)
                candidates = []
                for i in range(len(selected_indices)):
                    l = []
                    if label_en[i]:
                        l += [label_en[i]]
                    if label_ru[i]:
                        l += [label_en[i]]
                    if label_uk[i]:
                        l += [label_en[i]]
                    if alias_en[i]:
                        l += list(alias_en[i])
                    if alias_ru[i]:
                        l += list(alias_ru[i])
                    if alias_uk[i]:
                        l += list(alias_uk[i])
                    candidates.append(l)
                idx = select_most_overlapped(list(self.name), *candidates)
                return selected_indices[idx]

    @rltk.cached_property
    def selected_target_index(self):
        if self.target:
            selected_indices = highest_score_indices(self.target_score)
            if len(selected_indices) == 1:
                return selected_indices[0]
            else:
                idx = select_most_overlapped(self.name, *itemgetter(*selected_indices)(self.target_name))
                return selected_indices[idx]

    @rltk.cached_property
    def selected_wikidata(self):
        idx = self.selected_wikidata_index
        if idx is not None:
            return self.wikidata[idx]

    @rltk.cached_property
    def selected_target(self):
        idx = self.selected_target_index
        if idx is not None:
            return self.target[idx]

    @rltk.cached_property
    def selected_wikidata_labels(self):
        ret = []
        if self.selected_wikidata:
            # label
            if self.wikidata_label_en[self.selected_wikidata_index]:
                ret += [self.wikidata_label_en[self.selected_wikidata_index]]
            if self.wikidata_label_ru[self.selected_wikidata_index]:
                ret += [self.wikidata_label_ru[self.selected_wikidata_index]]
            if self.wikidata_label_uk[self.selected_wikidata_index]:
                ret += [self.wikidata_label_uk[self.selected_wikidata_index]]
            # alias
            if self.wikidata_alias_en[self.selected_wikidata_index]:
                ret += list(self.wikidata_alias_en[self.selected_wikidata_index])
            if self.wikidata_alias_ru[self.selected_wikidata_index]:
                ret += list(self.wikidata_alias_ru[self.selected_wikidata_index])
            if self.wikidata_alias_uk[self.selected_wikidata_index]:
                ret += list(self.wikidata_alias_uk[self.selected_wikidata_index])
        return ret

    @rltk.cached_property
    def selected_target_labels(self):
        if self.selected_target:
            return self.target_name[self.selected_target_index]
        return []

    @rltk.cached_property
    def concatenated_labels(self):
        ret = []
        if self.name:
            ret += self.name
        if self.selected_target:
            ret += self.selected_target_labels
        if self.selected_wikidata:
            ret += self.selected_wikidata_labels
        return set(ret)


# MAX_DISTANCE = 999999
class Cluster(object):
    def __init__(self, ds):
        self.all_records = set([])
        self.member_confidence = {}
        self.ds = ds
        self.type = None
        self.wd_id = None
        self.kb_id = None
        self.kb_labels = None
        self.wd_labels = None
        self.wd_candidate = {}
        self.name_labels = None

        self.prototype = None
        self.id_ = self.random_str(10)
        self.full_id = None
        self.feature_entity_id = None

    def elect_wd_id(self):
        if self.kb_id and len(self.wd_candidate) > 0:
            cand = list(self.wd_candidate.keys())
            idx = select_most_overlapped(self.kb_labels, *[self.wd_candidate[c] for c in cand])
            self.wd_id = cand[idx]
            self.wd_labels = self.wd_candidate[self.wd_id]

    @staticmethod
    def random_str(length=32):
        return ''.join([random.choice(string.ascii_letters + string.digits) for _ in range(length)])

    def similarity(self, r):
        return len(self.attractive_labels & set(r.name))

    def add(self, r):
        if isinstance(r, rltk.Record):
            r = r.id
        self.all_records.add(r)

    def compute_confidence(self):
        # for fake (singleton) cluster
        if not self.ds:
            for r in self.all_records:
                self.member_confidence[r] = 1.0
            return

        # create label -> entity id mapping
        all_labels = defaultdict(set)
        for r in self.all_records:
            for n in self.ds.get_record(r).name:
                all_labels[n].add(r)

        # count the total number each label appears in entities
        freq = {}
        for k, v in all_labels.items():
            freq[k] = len(v)
        total_freq = sum(freq.values())

        # confidence is based on the freq of the worst label
        attractive_labels = self.attractive_labels
        for r in self.all_records:
            score = 1.0
            for n in self.ds.get_record(r).name:
                if n in attractive_labels:  # only on the label not in attractive labels
                    continue
                score = min(score, round(1 * freq.get(n) / total_freq, 2))
            self.member_confidence[r] = score

    @property
    def attractive_labels(self):
        labels = set([])
        if self.kb_labels:
            labels |= self.kb_labels
        if self.wd_labels:
            labels |= self.wd_labels
        if self.name_labels:
            labels |= self.name_labels
        return labels

    def generate(self):
        self.compute_confidence()
        # self.feature_entity_id = deepcopy(self.all_records).pop()
        self.feature_entity_id = max(self.member_confidence.items(), key=lambda x: x[1])[0]  # the one with max confidence
        self.prototype = self.feature_entity_id #+ '-prototype-' + self.id_
        self.full_id = self.feature_entity_id + '-cluster-' + self.id_

    def debug(self):
        return {
            'wd_id': self.wd_id,
            'kb_id': self.kb_id,
            'wd_labels': list(self.wd_labels) if self.wd_labels else None,
            'kb_labels': list(self.kb_labels) if self.kb_labels else None,
            'name_labels': list(self.name_labels) if self.name_labels else None,
            'full_id': self.full_id,
            'prototype': self.prototype,
            'all_records': list(self.all_records),
            'member_confidence': self.member_confidence,
        }


def normalize_type(t):
    type_prefix = t.split('.')[0][len('ldcOnt:'):]
    if type_prefix in ('GPE', 'LOC'):
        return 'GeoLoc'
    return type_prefix


def process():

    df_entity = pd.DataFrame()

    logger.info('loading entity dataframes')
    for infile in glob.glob(os.path.join(config['temp_dir'], config['run_name'], '*/*.entity.h5')):
        source = os.path.basename(infile).split('.')[0]
        df_entity = df_entity.append(pd.read_hdf(infile))
    df_entity = df_entity.reset_index(drop=True)
    logger.info('Total number of entities: %d', len(df_entity))
    df_entity['type'] = df_entity['type'].apply(lambda x: x[0])  # only pick the fist type (compatible with old pipeline)
    df_entity_ori = df_entity.copy()

    ### filtering
    logger.info('filtering out some entity types')
    all_types = set(df_entity['type'])
    # all_types = set([t for tu in df_entity['type'] for t in tu])  # multi-type support
    selected_types = filter(lambda x: x.startswith(('ldcOnt:GPE', 'ldcOnt:LOC', 'ldcOnt:ORG', 'ldcOnt:PER')), all_types)
    df_entity = df_entity.loc[df_entity['type'].isin(selected_types)]
    # df_entity = df_entity.loc[[any([t in selected_types for t in tu]) for tu in df_entity['type']]] # multi-type support
    df_entity = df_entity[df_entity['name'].notnull()]
    df_entity = df_entity.where(pd.notnull(df_entity), None)
    df_entity_left = df_entity_ori[~df_entity_ori['e'].isin(df_entity['e'])]

    ### generate rltk components
    logger.info('generating rltk components')
    ds = rltk.Dataset(reader=rltk.DataFrameReader(df_entity), record_class=GaiaRecord)
    # for r in ds:
    #     print(r.concatenated_labels)
    #     print(r.name, r.target, r.wikidata, r.selected_target_index, r.selected_wikidata_index)
    bg_kb = rltk.TokenBlocker()
    blocks_kb = bg_kb.block(ds, function_=lambda r: [r.selected_target] if r.selected_target else ['None'])
    bg_wd = rltk.TokenBlocker()
    blocks_wd = bg_wd.block(ds, function_=lambda r: [r.selected_wikidata] if r.selected_wikidata else ['None'])


    ### clustering
    logger.info('clustering entity')
    # build cluster based on type
    all_clusters = []
    for bid, data in blocks_kb.key_set_adapter:
        if bid == 'None':
            continue

        c = Cluster(ds)
        for _, r_id in data:
            r = ds.get_record(r_id)
            if r.target and not c.kb_id:
                c.kb_id = r.selected_target
                c.kb_labels = set(r.selected_target_labels)
            if r.wikidata:
                if r.selected_wikidata not in c.wd_candidate:
                    c.wd_candidate[r.selected_wikidata] = set(r.selected_wikidata_labels)
            c.add(r)
        c.elect_wd_id()
        all_clusters.append(c)


    # find all wd only blocks
    wd_only_clusters = {}
    for bid, data in blocks_wd.key_set_adapter:
        if bid == 'None':
            continue

        wd_only_clusters[bid] = set()
        for _, r_id in data:
            r = ds.get_record(r_id)
            if r.selected_target:
                continue
            wd_only_clusters[bid].add(r_id)
        if len(wd_only_clusters[bid]) == 0:
            del wd_only_clusters[bid]

    # if wd block overlaps with kb clusters
    for c in all_clusters:
        if c.wd_id and c.wd_id in wd_only_clusters:
            for r in wd_only_clusters[c.wd_id]:
                c.add(r)
            del wd_only_clusters[c.wd_id]

    # construct clusters based on blocks
    for bid, cluster in wd_only_clusters.items():
        c = Cluster(ds)
        for r_id in cluster:
            c.add(r_id)
            r = ds.get_record(r_id)
            if not c.wd_id:
                c.wd_id = r.selected_wikidata
                c.wd_labels = set(r.selected_wikidata_labels)
        all_clusters.append(c)

    # validation
    # for idx, c in enumerate(all_clusters):
    #     if len(c.kb_id) > 1:
    #         logger.error('mulitple kb_ids in cluster: %s', c.kb_id)
    #         break
    #
    #     kb_ids = set()
    #     for r_id in c.all_records:
    #         r = ds.get_record(r_id)
    #         if r.selected_target:
    #             for id_ in r.selected_target:
    #                 kb_ids.add(id_)
    #     if len(kb_ids) > 1:
    #         logger.error('mulitple kb_ids in cluster: %s', kb_ids, c.kb_id)
    #         break

    # split based on types
    all_clusters_splitted = []
    for c in all_clusters:
        types = {}
        for r_id in c.all_records:
            r = ds.get_record(r_id)
            type_ = normalize_type(r.type)
            if type_ not in types:
                cc = Cluster(ds)
                cc.type = type_
                types[type_] = cc

            cc = types[type_]
            cc.add(r_id)
            cc.kb_id = c.kb_id
            cc.kb_labels = c.kb_labels
            cc.wd_id = c.wd_id
            cc.wd_labels = c.wd_labels

        for cc in types.values():
            all_clusters_splitted.append(cc)


    # merge singleton
    final_clusters = deepcopy(all_clusters_splitted)
    # MIN_SIM = 0.4
    clustered_entity_ids = set([r for c in all_clusters for r in c.all_records])

    for _, e in df_entity['e'].items():
        if e not in clustered_entity_ids:
            r = ds.get_record(e)
            r_type = normalize_type(r.type)
            local_best = [None, 0]  # first item: cluster id, second item: score
            for c in final_clusters:
                sim = c.similarity(r)
                if r_type != c.type:
                    continue
                if sim > local_best[1]:
                    local_best = [c, sim]

            c = local_best[0]
            if c is not None:
                c.add(r)
            else:
                # still singleton, construct singleton cluster
                c = Cluster(ds)
                c.type = r_type
                c.add(r)
                c.name_labels = set(r.name)
                final_clusters.append(c)

    # filtered-out entities
    # create cluster with fake record
    for _, e in df_entity_left.iterrows():
        c = Cluster(None)
        c.type = normalize_type(e['type'])
        c.add(e['e'])
        final_clusters.append(c)
    logger.info('Total number of clusters: %d', len(final_clusters))

    # create entity to cluster mapping
    entity_to_cluster = defaultdict(list)
    for c in final_clusters:
        for r in c.all_records:
            entity_to_cluster[r].append(c)
    for e, c in entity_to_cluster.items():
        if len(c) > 1:
            logger.error('Entity in multiple clusters detected, entity id: %s', e)

    ### generate cluster properties
    logger.info('generating cluster properties')
    for c in final_clusters:
        c.generate()

    ### export
    logger.info('exporting clusters')
    df_entity_cluster = df_entity_ori.copy()
    df_entity_cluster['cluster'] = None
    df_entity_cluster['synthetic'] = False
    df_entity_cluster['cluster_member_confidence'] = None

    logger.info('updating cluster info for each entity')
    for idx, e in df_entity_cluster['e'].items():
        clusters = list(set([c for c in entity_to_cluster[e]]))
        cluster_ids = tuple([c.full_id for c in clusters])
        confidences = tuple([c.member_confidence[e] for c in clusters])
        df_entity_cluster.at[idx, 'cluster'] = cluster_ids
        df_entity_cluster.at[idx, 'cluster_member_confidence'] = confidences

    logger.info('creating prototypes')
    proto_to_cluster_mapping = {}
    for c in final_clusters:
        proto_to_cluster_mapping[c.feature_entity_id] = c
    proto_dict = []
    for idx, row in df_entity_cluster.iterrows():
        eid = row['e']
        if eid not in proto_to_cluster_mapping:
            # not a prototype
            continue
        c = proto_to_cluster_mapping[eid]
        # p = df_entity_ori[df_entity_ori['e'] == c.feature_entity_id].iloc[0]
        row = row.to_dict()
        row['synthetic'] = True
        row['cluster'] = tuple([c.full_id])
        row['e'] = c.prototype
        proto_dict.append(row)
    df_prototypes = pd.DataFrame.from_dict(proto_dict)

    logger.info('appending dataframes')
    df_complete_entity_clusters = df_entity_cluster.append(df_prototypes)
    df_complete_entity_clusters.reset_index(drop=True)

    logger.info('writing to disk')
    output_file = os.path.join(config['temp_dir'], config['run_name'], 'entity_cluster')
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        df_complete_entity_clusters.to_hdf(output_file + '.h5', 'entity', mode='w', format='fixed')
        df_complete_entity_clusters.to_csv(output_file + '.h5.csv')
    with open(output_file + '.cluster.jl', 'w') as f:
        for c in final_clusters:
            f.write(json.dumps(c.debug()) + '\n')



if __name__ == '__main__':

    argv = sys.argv
    if argv[1] == 'process':
        process()
