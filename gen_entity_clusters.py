import pandas as pd
import rltk
import json
import random
import string
import itertools

MAX_DISTANCE = 999999


def random_str(N):
    return ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(N))


class Cluster(object):
    def __init__(self, cid, ds):
        self.cid = cid
        self.attractive_records = set([])  # contribute to clustering
        self.all_records = set([])
        self.ds = ds
        self.type = None
        self.fbids = set([])

    @staticmethod
    def record_score(r1, r2):
        score = rltk.jaccard_index_similarity(set(r1.concatenated_labels), set(r2.concatenated_labels))
        return score

    def distance(self, r):
        if r.type != self.type:
            return MAX_DISTANCE

        score = max([self.record_score(r, self.ds.get_record(rr)) for rr in self.attractive_records])
        if score == 0:
            return MAX_DISTANCE
        return 1 / score

    def add(self, r, contribute=True):
        if isinstance(r, rltk.Record):
            r = r.id
        if contribute:
            self.attractive_records.add(r)
        self.all_records.add(r)

    def print(self):
        print(self.cid, '\n  members: ', self.all_records, '\n  fbids: ', self.fbids)


def concat_list(*arr):
    ret = []
    for a in arr:
        if a:
            ret += a
    return ret


def concat_raw_object_list(ins, *keys):
    arr = []
    for k in keys:
        v = ins.raw_object[k]
        if isinstance(v, (list, tuple)):
            arr += v
        else:
            arr.append(v)
    return concat_list(arr)


@rltk.set_id('e')
class GaiaRecord(rltk.AutoGeneratedRecord):
    
    @rltk.cached_property
    def concatenated_labels(self):
        return concat_raw_object_list(
            self,
            'name', 'transl_name',
            'wiki_label_en', 'wiki_label_ru', 'wiki_label_uk', 
            'wiki_alias_en', 'wiki_alias_ru', 'wiki_alias_uk')

    def __eq__(self, other):
        return self.id == other.id


def merge_clusters(c1, c2, ds):
    c = Cluster(c1.cid, ds)
    for r in c1.all_records:
        c.add(r)
    for r in c2.all_records:
        if r not in c.all_records:
            c.add(r)
    c.fbids = set().union(c1.fbids, c2.fbids)
    return c


def has_freebase(s):
    if s is not None and len(s) > 0:
        for fbid in s:
            if 'NIL' not in fbid:
                return True
    return False


def gen_entity_clusters_baseline(entity_h5, outdir):
    df_entity = pd.read_hdf(entity_h5)
    # df_entity['has_freebase'] = df_entity['fbid_type'].apply(lambda x: x == 'm')
    df_entity['has_freebase'] = df_entity['fbid'].apply(has_freebase)
    df_entity['has_target'] = df_entity['target'].apply(lambda x: x is not None and 'NIL' not in x)
    df_entity.head()

    set(df_entity['type'])

    # df_entity = df_entity.loc[df_entity['type'].isin([
    #     'ldcOnt:Person',
    #     'ldcOnt:Person.MilitaryPersonnel',
    #     'ldcOnt:Person.MilitaryPersonnel.MilitaryOfficer',
    #     'ldcOnt:Organization',
    #     'ldcOnt:Organization.Association',
    #     'ldcOnt:Organization.Association.Club',
    #     'ldcOnt:Organization.CommercialOrganization.BroadcastingCompany',
    #     'ldcOnt:Organization.CommercialOrganization.Manufacturer',
    #     'ldcOnt:Organization.Government',
    #     'ldcOnt:Organization.Government.Agency',
    #     'ldcOnt:Organization.Government.LegislativeBody',
    #     'ldcOnt:Organization.International',
    #     'ldcOnt:Organization.MilitaryOrganization.GovernmentArmedForces',
    #     'ldcOnt:Organization.PoliticalOrganization.Party',
    #     'ldcOnt:GeopoliticalEntity',
    #     'ldcOnt:GeopoliticalEntity.Country.Country',
    #     'ldcOnt:GeopoliticalEntity.OrganizationOfCountries.OrganizationOfCountries',
    #     'ldcOnt:GeopoliticalEntity.UrbanArea.City',
    #     'ldcOnt:Location',
    #     'ldcOnt:Location.Land',
    #     'ldcOnt:Location.Land.Continent',
    #     'ldcOnt:Location.Position.Region',
    #     'ldcOnt:Commodity.Document'
    # ])]
    df_entity[df_entity['wikidata'].notnull()].head()

    df_entity_filtered = df_entity[(df_entity.has_freebase | df_entity.has_target)]
    df_entity_filtered = df_entity_filtered.drop_duplicates(subset=['e', 'target', 'fbid'])

    # # Create RLTK components
    # ds = rltk.Dataset(reader=rltk.DataFrameReader(df_entity), record_class=GaiaRecord)
    ds = rltk.Dataset(reader=rltk.DataFrameReader(df_entity_filtered), record_class=GaiaRecord)

    bg = rltk.HashBlockGenerator()
    blocks = bg.block(ds, function_=lambda r: r.target if r.has_target else 'None')
    # blocks = bg.block(ds, function_=lambda r: r.fbid if r.has_freebase else 'None')
    # b1_inverted = rltk.BlockingHelper.generate_inverted_indices(b1)
    # b2_inverted = rltk.BlockingHelper.generate_inverted_indices(b2)
    # blocks = rltk.BlockingHelper.union(b1, b1_inverted, b2, b2_inverted)
    # blocks = bg.block(ds, function_=lambda r: r.target if r.target else 'None')

    sum(1 for _ in blocks.key_set_adapter)

    num_in_block = []
    for b, data in blocks.key_set_adapter:
        num_in_block.append(len(data))

    from collections import Counter
    dict(sorted(Counter(num_in_block).items()))

    # Cluster baseline #

    # clusters based on target
    clusters = {}
    for cid, data in blocks.key_set_adapter:
        if cid != 'None':
            c = Cluster(cid, ds)
            for _, rid in data:
                r = ds.get_record(rid)
                c.add(r)
                fbids = r.fbid
                if fbids:
                    for fbid in fbids:
                        c.fbids.add(fbid)
            clusters[cid] = c

    print("merging")
    res = 1
    while res != 0:
        try:
            for cid1, cid2 in itertools.combinations(clusters, 2):
                if cid1 != cid2:
                    c1 = clusters[cid1]
                    c2 = clusters[cid2]
                    if bool(c1.fbids & c2.fbids):  # has overlap
                        # merge and add, delete cluster, cluster, break
                        print('merge ', cid2, ' -->', cid1)
                        new_cluster = merge_clusters(c1, c2, ds)
                        clusters[cid1] = new_cluster
                        del clusters[cid2]
                        raise Exception("break")
            res = 0
        except Exception:
            res = 1

    # Try to merge those in 'None' or put them in singleton if it has freebase id
    for _, rid in blocks.get('None'):
        r = ds.get_record(rid)
        merged = False
        if r.has_freebase:
            print(r.id, r.target, r.fbid)
            for cid, c in clusters.items():
                r_fbids = set([f for f in r.fbid])
                if bool(r_fbids & c.fbids) or cid in r.fbid:
                    c.add(r)
                    print('    --> ', c.cid)
                    merged = True
                    break
            if not merged:
                c = Cluster(r.fbid[0], ds)
                for fbid in r.fbid:
                    c.fbids.add(fbid)
                c.add(r)
                clusters[c.cid] = c
                print('    new ', c.cid)

    all_clusters = clusters.values()

    # build cluster based on type
    # all_clusters = []
    # block_and_cluster = {}
    # for bid, data in blocks.key_set_adapter:
    #     clusters = {}
    #     for _, r_id in data:
    #         r = ds.get_record(r_id)
    #
    #         if bid == 'None':
    #             continue
    #
    #         type_ = r.type
    #         if type_ not in clusters:
    #             c = Cluster(ds)
    #             c.type = type_
    #             c.add(r)
    #             clusters[type_] = c
    #         else:
    #             clusters[type_].add(r)
    #
    #     block_and_cluster[bid] = clusters
    #
    #     for c in clusters.values():
    #         all_clusters.append(c)
    #
    # bsize = set([])
    # i = 0
    # for k, v in block_and_cluster.items():
    #     bsize.add(len(v))
    #     print(k, v)
    #     i += 1
    #     if i == 100:
    #         break
    #
    # df_entity[df_entity['fbid'] == 'LDC2015E42:m.0372_h'][['e', 'type', 'name', 'source', 'fbid']].groupby('e').head(1)

    def debug_output(c, type_):
        j = {'attractive_records': list(c.attractive_records), 'all_records': {}, 'type': type_}
        for rid in c.all_records:
            j['all_records'][rid] = ds.get_record(rid).__dict__
        return j

    with open(outdir + '/entity-clusters.jl', 'w') as f:
        for c in all_clusters:
            f.write(json.dumps(list(c.all_records)) + '\n')
    with open(outdir + '/entity-clusters-debug.jl', 'w') as f:
        for c in all_clusters:
            f.write(json.dumps(debug_output(c, 'baseline')) + '\n')




