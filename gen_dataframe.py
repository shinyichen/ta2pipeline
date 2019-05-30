from gastrodon import RemoteEndpoint,QName,ttl,URIRef,inline
import pandas as pd
import json
from gastrodon import _parseQuery
from SPARQLWrapper import SPARQLWrapper, N3
from rdflib import Graph
from model.source import LTFSourceContext
from rdflib.plugins.stores.sparqlstore import SPARQLStore
from rdflib.namespace import Namespace, RDFS, SKOS
from rdflib import URIRef, Literal


# wikidata_sparql = SPARQLStore("http://sitaware.isi.edu:8080/bigdata/namespace/wdq/sparql")
wikidata_sparql = SPARQLStore("https://query.wikidata.org/sparql")
WDT = Namespace('http://www.wikidata.org/prop/direct/')
namespaces = {'wdt': WDT, 'skos': SKOS}

namespaces_str = """
@prefix : <https://tac.nist.gov/tracks/SM-KBP/2018/ontologies/AidaDomainOntologiesCommon#> .
@prefix aida: <https://tac.nist.gov/tracks/SM-KBP/2019/ontologies/InterchangeOntology#> .
@prefix dc: <http://purl.org/dc/elements/1.1/> .
@prefix domainOntology: <https://tac.nist.gov/tracks/SM-KBP/2019/ontologies/SeedlingOntology> .
@prefix ldc: <https://tac.nist.gov/tracks/SM-KBP/2019/ontologies/LdcAnnotations#> .
@prefix ldcOnt: <https://tac.nist.gov/tracks/SM-KBP/2019/ontologies/LDCOntology#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
"""

# namespaces_str = """
# @prefix : <https://tac.nist.gov/tracks/SM-KBP/2018/ontologies/AidaDomainOntologiesCommon#> .
# @prefix aida: <https://tac.nist.gov/tracks/SM-KBP/2018/ontologies/InterchangeOntology#> .
# @prefix dc: <http://purl.org/dc/elements/1.1/> .
# @prefix domainOntology: <https://tac.nist.gov/tracks/SM-KBP/2018/ontologies/SeedlingOntology> .
# @prefix ldc: <https://tac.nist.gov/tracks/SM-KBP/2018/ontologies/LdcAnnotations#> .
# @prefix ldcOnt: <https://tac.nist.gov/tracks/SM-KBP/2018/ontologies/LDCOntology#> .
# @prefix owl: <http://www.w3.org/2002/07/owl#> .
# @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
# @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
# @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
# @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
# """


def query_context(source, start, end):
    if start == -1 or end == -1:
        return None
    context_extractor = LTFSourceContext(source)
    if context_extractor.doc_exists():
        return context_extractor.query_context(start, end)


def query_label(source, start, end):
    if start == -1 or end == -1:
        return None
    context_extractor = LTFSourceContext(source)
    if context_extractor.doc_exists():
        text = context_extractor.query(start, end)
        return text


def getFBIDs(s):
    fbids = json.loads(s).get('freebase_link').keys()
    return tuple(i for i in fbids)


def link_wikidata(fbid):
    if not fbid or 'NIL' in fbid:  # fbid.startswith('LDC2015E42:NIL'):
        return None
    fbid = '/' + fbid.replace('.', '/')
    query = "SELECT ?qid WHERE { ?qid wdt:P646 ?freebase } LIMIT 1"
    for qid, in wikidata_sparql.query(query, namespaces, {'freebase': Literal(fbid)}):
        return str(qid)


def get_labels(pred, lang):
    def get_labels_for_entity(qid):
        if not qid:
            return None
        query = """
        SELECT ?label 
        WHERE { 
            ?qid pred ?label
            FILTER (lang(?label) = "language") }
        """.replace('pred', pred).replace('language', lang)
        labels = []
        for label, in wikidata_sparql.query(query, namespaces, {'qid': URIRef(qid)}):
            labels.append(str(label))
        return tuple(labels)

    return get_labels_for_entity


def to_int(s):
    return int(s) if isinstance(s, str) or isinstance(s, int) else -1


def generate_dataframe(endpoint_url, outdir):
    endpoint = RemoteEndpoint(url=endpoint_url, prefixes=inline(namespaces_str).graph)

    def describe(self, sparql: str):
        return self._describe(sparql).serialize(format='n3').decode()

    def _describe(self, sparql: str):
        that = endpoint._wrapper()
        that.setQuery(endpoint._prepend_namespaces(sparql, _parseQuery))
        that.setReturnFormat(N3)
        results = that.query().convert()
        g = Graph()
        g.parse(data=results, format="n3")
        return g

    RemoteEndpoint.describe = describe
    RemoteEndpoint._describe = _describe

    entities = endpoint.select("""
    SELECT DISTINCT ?e {
        ?e a aida:Entity ;
           aida:system <http://www.rpi.edu> ;
    }
    """)

    df = endpoint.select("""
        SELECT DISTINCT ?e ?fbid {
        ?e a aida:Entity ;
           aida:system <http://www.rpi.edu> ;
           aida:privateData [
                aida:jsonContent ?fbid ;
                aida:system <http://www.rpi.edu/EDL_Freebase>
            ]
        }
    """)

    df.fbid = df.fbid.apply(lambda s: getFBIDs(s) if s else None)
    df = df.astype({
        'e': str, 'fbid': object
    })
    rpi_external = df

    rpi_fbid = rpi_external.fbid.apply(pd.Series).merge(rpi_external, right_index=True, left_index=True).drop(['fbid'], axis=1).melt(id_vars=['e'], value_name="fbid").drop("variable", axis=1).dropna()
    rpi_fbid.drop_duplicates()

    df = endpoint.select("""
    SELECT DISTINCT ?e ?type ?label ?target ?source ?start ?end ?justificationType {
        ?e a aida:Entity ;
           aida:system <http://www.rpi.edu> ;
           ^rdf:subject [
            a rdf:Statement ;
            rdf:predicate rdf:type ;
            rdf:object ?type ;
            aida:justifiedBy ?justification ]
        OPTIONAL { ?justification aida:privateData [
                aida:jsonContent ?label ;
                aida:system <http://www.rpi.edu/EDL_Translation> ]}
        OPTIONAL { ?e aida:link/aida:linkTarget ?target }
        OPTIONAL { ?justification aida:source ?source }
        OPTIONAL { ?justification aida:startOffset ?start }
        OPTIONAL { ?justification aida:endOffsetInclusive ?end }
        OPTIONAL { ?justification aida:privateData [ 
                aida:system <http://www.rpi.edu> ;
                aida:jsonContent ?justificationType ] }
    }
    """)
    df.start = df.start.apply(to_int)
    df.end = df.end.apply(to_int)
    df.justificationType = df.justificationType.apply(lambda s: json.loads(s).get('justificationType'))
    df.label = df.label.apply(lambda s: tuple(json.loads(s).get('translation')) if s else None)
    df = df.astype({
        'e': str, 'type': str, 'target': str, 'source': str, 'start': int, 'end': int, 'justificationType': str
    })
    rpi_entity_with_justification = df

    df = endpoint.select("""
    SELECT DISTINCT ?e ?type ?name ?text ?target ?source {
        ?e a aida:Entity ;
           aida:justifiedBy/aida:source ?source ;
           aida:system <http://www.rpi.edu> .
        ?statement a rdf:Statement ;
                   rdf:subject ?e ;
                   rdf:predicate rdf:type ;
                   rdf:object ?type .
        OPTIONAL { ?e aida:hasName ?name }
        OPTIONAL { ?e aida:textValue ?text }
        OPTIONAL { ?e aida:link/aida:linkTarget ?target }
    }
    """)
    df = df.astype({
        'e': str, 'type': str, 'name': str, 'target': str, 'source': str, 'text': str
    })
    rpi_entity_valid = df

    # Relations

    df = endpoint.select("""
    SELECT DISTINCT ?e ?type ?source ?start ?end {
        ?e a aida:Relation ;
           aida:system <http://www.rpi.edu> .
        ?statement a rdf:Statement ;
                   rdf:subject ?e ;
                   rdf:predicate rdf:type ;
                   rdf:object ?type ;
                   aida:justifiedBy ?justification 
        OPTIONAL { ?justification aida:source ?source }
        OPTIONAL { ?justification aida:startOffset ?start }
        OPTIONAL { ?justification aida:endOffsetInclusive ?end }
    }
    """)
    df.start = df.start.apply(to_int)
    df.end = df.end.apply(to_int)
    df = df.astype({
        'e': str, 'type': str, 'source': str, 'start': int, 'end': int
    })
    rpi_relation = df

    df = endpoint.select("""
    SELECT DISTINCT ?e ?p ?o {
        ?e a aida:Relation ;
           aida:system <http://www.rpi.edu> .
        ?statement a rdf:Statement ;
                   rdf:subject ?e ;
                   rdf:predicate ?p ;
                   rdf:object ?o 
        FILTER (?p != rdf:type)
    }
    """)
    df = df.astype({
        'e': str, 'p': str, 'o': str
    })
    rpi_relation_roles = df

    # Documents

    df = endpoint.select("""
    SELECT DISTINCT ?source ?fileType {
        ?justification a aida:TextJustification ;
                       aida:system <http://www.rpi.edu> ;
                       aida:source ?source ;
                       aida:privateData ?filePrivate .
        ?filePrivate aida:system <http://www.rpi.edu/fileType> ;
                     aida:jsonContent ?fileType
    }
    """)
    df['lang'] = df.fileType.apply(lambda s: json.loads(s).get('fileType'))
    df = df.drop(columns='fileType')
    df = df.astype({
        'source': str, 'lang': str
    })
    document_types = df

    rpi_entity_with_justification.to_hdf(outdir + '/entity_with_labels.h5', 'entity', mode='w', format='fixed')
    rpi_entity_valid.to_hdf(outdir + '/entity_valid.h5', 'entity', mode='w', format='fixed')
    rpi_relation.to_hdf(outdir + '/relation.h5', 'entity', mode='w', format='fixed')
    rpi_relation_roles.to_hdf(outdir + '/relation_roles.h5', 'entity', mode='w', format='fixed')
    document_types.to_hdf(outdir + '/document.h5', 'entity', mode='w', format='fixed')
    _ = pd.read_hdf(outdir + '/entity_with_labels.h5')
    _ = pd.read_hdf(outdir + '/entity_valid.h5')
    _ = pd.read_hdf(outdir + '/relation.h5')
    _ = pd.read_hdf(outdir + '/relation_roles.h5')
    _ = pd.read_hdf(outdir + '/document.h5')

    # Transform Entities

    # 1. `name`

    df = rpi_entity_valid
    df['name'] = df.apply(lambda r: r['name'] if r['name'] != 'None' else None, axis=1)
    df = df.drop(columns='text')
    df = df.drop_duplicates()
    df = df[['e', 'type', 'target', 'source']].groupby('e').head(1).join(df.groupby('e')['name'].apply(tuple), on='e')
    df['name'] = df['name'].apply(lambda s: s if s[0] else None)
    df_names = df

    # 2. origin

    rpi_entity_with_justification['origin'] = rpi_entity_with_justification.apply(lambda r: query_context(r.source, r.start, r.end), axis=1)
    rpi_entity_with_justification['originLabel'] = rpi_entity_with_justification.apply(
        lambda r: query_label(r.source, r.start, r.end), axis=1)

    df = rpi_entity_with_justification
    # drop entities with nominal mention and pronominal mention
    # comment out line below to generate for all entities
    # df = df[(df['justificationType']!='nominal_mention') & (df['justificationType']!='pronominal_mention')]
    df['debug'] = df['justificationType'].apply(
        lambda s: False if s != 'nominal_mention' and s != 'pronominal_mention' else True)
    rpi_entity_with_justification_filtered = df

    df_origin = df[['e', 'origin']].groupby('e')['origin'].apply(tuple).to_frame()
    df_origin['origin'] = df_origin['origin'].apply(lambda s: s if s[0] else None)

    df_origin_label = df[['e', 'originLabel']].groupby('e')['originLabel'].apply(tuple).to_frame()
    df_origin_label = df_origin_label['originLabel'].apply(lambda s: s if s[0] else None)

    # 3. wikidata and wikidata labels, alias

    df_fbid = rpi_fbid[['fbid']].drop_duplicates()
    df_fbid['wikidata'] = df_fbid.fbid.apply(link_wikidata)
    df_fbid['wiki_label_en'] = df_fbid['wikidata'].apply(get_labels('rdfs:label', 'en'))
    df_fbid['wiki_label_ru'] = df_fbid['wikidata'].apply(get_labels('rdfs:label', 'ru'))
    df_fbid['wiki_label_uk'] = df_fbid['wikidata'].apply(get_labels('rdfs:label', 'uk'))
    df_fbid['wiki_alias_en'] = df_fbid['wikidata'].apply(get_labels('skos:altLabel', 'en'))
    df_fbid['wiki_alias_ru'] = df_fbid['wikidata'].apply(get_labels('skos:altLabel', 'ru'))
    df_fbid['wiki_alias_uk'] = df_fbid['wikidata'].apply(get_labels('skos:altLabel', 'uk'))
    df_fbid = df_fbid.where(pd.notnull(df_fbid), None)

    def add_wd(fbids):
        if fbids:
            wd = []
            label_en = ()
            label_ru = ()
            label_uk = ()
            alias_en = ()
            alias_ru = ()
            alias_uk = ()
            for fbid in fbids:
                row_df = df_fbid.loc[df_fbid.fbid == fbid]

                wikidata = row_df['wikidata'].values[0]
                if wikidata:
                    wd.append(wikidata)

                wiki_label_en = row_df['wiki_label_en'].values[0]
                if wiki_label_en:
                    label_en = label_en + wiki_label_en
                wiki_label_ru = row_df['wiki_label_ru'].values[0]
                if wiki_label_ru:
                    label_ru = label_ru + wiki_label_ru
                wiki_label_uk = row_df['wiki_label_uk'].values[0]
                if wiki_label_uk:
                    label_uk = label_uk + wiki_label_uk

                wiki_alias_en = row_df['wiki_alias_en'].values[0]
                if wiki_alias_en:
                    alias_en = alias_en + wiki_alias_en
                wiki_alias_ru = row_df['wiki_alias_ru'].values[0]
                if wiki_alias_ru:
                    alias_ru = alias_ru + wiki_alias_ru
                wiki_alias_uk = row_df['wiki_alias_uk'].values[0]
                if wiki_alias_uk:
                    alias_uk = alias_uk + wiki_alias_uk
            return pd.Series(
                {'wikidata': tuple(wd), 'wiki_label_en': label_en, 'wiki_label_ru': label_ru, 'wiki_label_uk': label_uk,
                 'wiki_alias_en': alias_en, 'wiki_alias_ru': alias_ru, 'wiki_alias_uk': alias_uk})
        else:
            return pd.Series({'wikidata': None, 'wiki_label_en': None, 'wiki_label_ru': None, 'wiki_label_ru': None,
                              'wiki_alias_en': None, 'wiki_alias_ru': None, 'wiki_alias_uk': None})

    df = rpi_entity_with_justification_filtered[['e', 'type', 'label', 'source', 'target', 'debug']]\
        .drop_duplicates()\
        .join(df_origin, on='e')\
        .join(df_origin_label, on='e')
    df = df.join(rpi_external.set_index('e'), on='e')
    df = df.where(pd.notnull(df), None)
    df[['wikidata', 'wiki_label_en', 'wiki_label_ru', 'wiki_label_uk', 'wiki_alias_en', 'wiki_alias_ru',
        'wiki_alias_uk']] = df['fbid'].apply(add_wd)

    df = df.join(document_types.set_index('source'), on='source')
    df = df.join(df_names[['e', 'name']].set_index('e'), on='e')
    df = df[['e', 'type', 'name', 'source', 'target', 'fbid', 'wikidata',
             'wiki_label_en', 'wiki_label_ru', 'wiki_label_uk', 'wiki_alias_en',
             'wiki_alias_ru', 'wiki_alias_uk', 'origin', 'originLabel', 'lang', 'label', 'debug']]
    df_all = df

    df_all.to_hdf(outdir + '/entity_all.h5', 'entity', mode='w', format='fixed')
    _ = pd.read_hdf(outdir + '/entity_all.h5')

    df_all.to_csv(outdir + '/entity_all.csv')


