if(__name__ == "__main__"):
    import sys
    sys.path.append("../")

from pprint import pprint
from concept_formation.cobweb3 import Cobweb3Node
from concept_formation.cobweb import CobwebNode
from concept_formation.preprocessor import NameStandardizer
from concept_formation.structure_mapper import StructureMapper
from concept_formation.structure_mapper import rename_flat
from concept_formation.structure_mapper import contains_component
from learners.IncrementalHeuristic import IncrementalHeuristic
from planners.fo_planner import Operator
from planners.fo_planner import build_index
from planners.fo_planner import subst
import numpy as np
import itertools

global my_gensym_counter
my_gensym_counter = 0


def ground(arg):
    if isinstance(arg, tuple):
        return tuple(ground(e) for e in arg)
    elif isinstance(arg, str):
        return arg.replace('?', 'QM')
    else:
        return arg


def unground(arg):
    if isinstance(arg, tuple):
        return tuple(unground(e) for e in arg)
    elif isinstance(arg, str):
        return arg.replace('QM', '?')
    else:
        return arg


class Counter(object):

    def __init__(self):
        self.count = 0

    def increment(self):
        self.count += 1


class BaseILP(object):

    def __init__(self, args, G):
        pass

    def check_match(self, t, x):
        pass

    def get_match(self, X):
        pass

    def get_matches(self, X):
        pass

    def ifit(self, X, y):
        pass

    def fit(self, X, y):
        """
        Assume that X is a list of dictionaries that represent FOL using
        TRESTLE notation.

        y is a vector of 0's or 1's that specify whether the examples are
        positive or negative.
        """
        pass


def value_gensym():
    """
    Generates unique names for naming renaming apart objects.

    :return: a unique object name
    :rtype: '?val'+counter
    """
    global my_gensym_counter
    my_gensym_counter += 1
    return '?val' + str(my_gensym_counter)


# def gensym():
#     """
#     Generates unique names for naming renaming apart objects.
#
#     :return: a unique object name
#     :rtype: '?o'+counter
#     """
#     global my_gensym_counter
#     my_gensym_counter += 1
#     return '?o' + str(my_gensym_counter)


def get_vars(arg):
    if isinstance(arg, tuple):
        lst = []
        for e in arg:
            for v in get_vars(e):
                if v not in lst:
                    lst.append(v)
        return lst
    elif isinstance(arg, str) and len(arg) > 0 and arg[0] == '?':
        return [arg]
    else:
        return []


class WhereLearner(object):

    def __init__(self, learner_name, learner_kwargs={}):
        self.learner_name = learner_name
        self.learner_kwargs = learner_kwargs
        self.rhs_by_label = {}
        self.learners = {}

    def add_rhs(self, rhs, constraints):
        # args = [skill.selection_var] + skill.input_vars
        self.learners[rhs] = get_where_sublearner(self.learner_name,
            args=tuple(rhs.all_vars), constraints=constraints, **self.learner_kwargs)

        rhs_list = self.rhs_by_label.get(rhs.label, [])
        rhs_list.append(rhs)
        self.rhs_by_label[rhs.label] = rhs_list

    def check_match(self, rhs, t, x):
        return self.learners[rhs].check_match(t, x)

    def get_match(self, rhs, X):
        # args = [skill.selection_var] + skill.input_vars
        return self.learners[rhs].get_match(X)

    def get_matches(self, rhs, X):
        # args = [skill.selection_var] + skill.input_vars
        return self.learners[rhs].get_matches(X)

    def ifit(self, rhs, t, X, y):
        # args = [skill.selection_var] + skill.input_vars
        return self.learners[rhs].ifit(t, X, y)

    def fit(self, rhs, T, X, y):
        return self.learners[rhs].fit(T, X, y)

    def get_strategy(self):
        return WHERE_STRATEGY[self.learner_name.lower().replace(" ","").replace("_","")]

    def skill_info(self,rhs):
        return self.learners[rhs].skill_info()


class MostSpecific(BaseILP):
    """
    This learner always returns the tuples it was trained with, after ensuring
    they meet any provided constraints.
    """
    def __init__(self, args, constraints=None):
        self.pos_count = 0
        self.neg_count = 0
        self.args = args
        self.tuples = set()

        if constraints is None:
            self.constraints = frozenset()
        else:
            self.constraints = constraints

    def num_pos(self):
        return self.pos_count

    def num_neg(self):
        return self.neg_count

    def __len__(self):
        return self.pos_count + self.neg_count

    def __repr__(self):
        return repr(self.tuples)

    def __str__(self):
        return str(self.tuples)

    def ground_example(self, x):
        grounded = [tuple(list(ground(a)) + [ground(x[a])])
                    if isinstance(a, tuple)
                    else tuple([ground(a), ground(x[a])]) for a in x]
        return grounded

    def check_match(self, t, x):
        x = x.get_view("flat_ungrounded")
        # print("CHECK MATCHES T", t)

        t = tuple(ground(ele) for ele in t)

        # Update to include initial args
        mapping = {a: t[i] for i, a in enumerate(self.args)}


        if t not in self.tuples:
            return False

        grounded = self.ground_example(x)
        index = build_index(grounded)

        # Update to include initial args
        operator = Operator(tuple(('Rule',) + self.args),
                            frozenset().union(self.constraints), [])
        for m in operator.match(index, initial_mapping=mapping):
            return True
        return False

    def get_matches(self, x, epsilon=0.0):
        x = x.get_view("flat_ungrounded")

        grounded = self.ground_example(x)

        index = build_index(grounded)

        for t in self.tuples:
            mapping = {a: t[i] for i, a in enumerate(self.args)}
            operator = Operator(tuple(('Rule',) + self.args),
                                frozenset().union(self.constraints), [])

            for m in operator.match(index, epsilon=epsilon,
                                    initial_mapping=mapping):
                result = tuple(ele.replace("QM", '?') for ele in t)
                yield result
                break


    def ifit(self, t, x, y):
        # print("TUPIN", t)

        if y > 0:
            self.pos_count += 1
        else:
            self.neg_count += 1

        t = tuple(ground(e) for e in t)
        self.tuples.add(t)


class StateResponseLearner(BaseILP):
    """
    This just memorizes pairs of states and matches. Then given a state it
    looks up a match.
    """

    def __init__(self, remove_attrs=None):
        self.states = {}
        self.target_types = []
        self.pos_concept = Counter()
        self.neg_concept = Counter()

        if remove_attrs is None:
            remove_attrs = ['value']
        self.remove_attrs = remove_attrs

    def num_pos(self):
        return self.pos_concept.count()

    def num_neg(self):
        return self.neg_concept.count()

    def ifit(self, t, x, y):
        if y == 0:
            self.neg_concept.increment()
            return
        self.pos_concept.increment()

        x = {a: x[a] for a in x if (isinstance(a, tuple) and a[0] not in
                                    self.remove_attrs) or
                                   (not isinstance(a, tuple) and a not in
                                    self.remove_attrs)}

        x = frozenset(x.items())
        # pprint(x)
        if x not in self.states:
            self.states[x] = set()
        self.states[x].add(tuple(t))

    def get_matches(self, x, epsilon=0.0):
        x = {a: x[a] for a in x if (isinstance(a, tuple) and a[0] not in
                                    self.remove_attrs) or
                                   (not isinstance(a, tuple) and a not in
                                    self.remove_attrs)}
        x = frozenset(x.items())
        if x not in self.states:
            return
        for t in self.states[x]:
            yield t

    def check_match(self, t, x):
        # t = tuple('?' + e for e in t)
        # print("CHECKING", t)
        # print("against", [self.states[a] for a in self.states])

        x = {a: x[a] for a in x if (isinstance(a, tuple) and a[0] not in
                                    self.remove_attrs) or
                                   (not isinstance(a, tuple) and a not in
                                    self.remove_attrs)}
        x = frozenset(x.items())

        # if t in [self.states[a] for a in self.states][0]:
        #     print("KEY")
        #     pprint([a for a in self.states][0])
        #     print("THE X")
        #     pprint(x)

        return x in self.states and t in self.states[x]

    def __len__(self):
        return sum(len(self.states[x]) for x in self.states)

    def fit(self, T, X, y):
        for i, t in enumerate(T):
            self.ifit(T[i], X[i], y[i])


class RelationalLearner(BaseILP):

    def __init__(self, args, constraints=None, remove_attrs=None):
        self.pos_count = 0
        self.neg_count = 0
        self.args = args

        # self.learner = IncrementalGeneralToSpecific(args=self.args,
        #                                             constraints=constraints)
        # self.learner = IncrementalSpecificToGeneral(args=self.args,
        #                                             constraints=constraints)
        self.learner = IncrementalHeuristic(args=self.args,
                                            constraints=constraints)

        if remove_attrs is None:
            remove_attrs = ['value']
        self.remove_attrs = remove_attrs

    def num_pos(self):
        return self.pos_count

    def num_neg(self):
        return self.neg_count

    def __len__(self):
        return self.pos_count + self.neg_count

    def __repr__(self):
        return repr(self.learner.get_hset())

    def __str__(self):
        return str(self.learner.get_hset())

    def ground_example(self, x):
        grounded = [tuple(list(ground(a)) + [ground(x[a])])
                    if isinstance(a, tuple)
                    else tuple([ground(a), ground(x[a])]) for a in x]
        return grounded

    def check_match(self, t, x):
        # print("CHECK MATCHES T", t)

        t = tuple(ele.replace('?', "QM") for ele in t)

        # Update to include initial args
        mapping = {a: t[i] for i, a in enumerate(self.args)}

        # print("MY MAPPING", mapping)

        # print("CHECKING MATCHES")
        grounded = self.ground_example(x)
        # grounded = [(ground(a), x[a]) for a in x if (isinstance(a, tuple))]
        # pprint(grounded)
        # pprint(mapping)
        index = build_index(grounded)

        for h in self.learner.get_hset():
            # Update to include initial args
            operator = Operator(tuple(('Rule',) + self.args), h, [])
            for m in operator.match(index, initial_mapping=mapping):
                return True
        return False

    def get_matches(self, x, epsilon=0.0):

        # print("GETTING MATCHES")
        # pprint(self.learner.get_hset())
        grounded = self.ground_example(x)
        # grounded = [(ground(a), x[a]) for a in x if (isinstance(a, tuple))]
        # print("FACTS")

        # pprint(grounded)

        index = build_index(grounded)

        # print("INDEX")
        # pprint(index)

        # print("OPERATOR")
        # pprint(self.operator)
        # print(self.learner.get_hset())

        for h in self.learner.get_hset():
            # print('h', h)
            # Update to include initial args
            operator = Operator(tuple(('Rule',) + self.args), h, [])
            # print("OPERATOR", h)

            for m in operator.match(index, epsilon=epsilon):
                # print('match', m, operator.name)
                result = tuple([unground(subst(m, ele))
                                for ele in operator.name[1:]])
                # result = tuple(['?' + subst(m, ele)
                #                 for ele in self.operator.name[1:]])
                # result = tuple(['?' + m[e] for e in self.target_types])
                # print('GET MATCHES T', result)
                yield result

        # print("GOT ALL THE MATCHES!")

    def ifit(self, t, x, y):

        if y == 1:
            self.pos_count += 1
        else:
            self.neg_count += 1

        t = tuple(ground(e) for e in t)
        grounded = self.ground_example(x)

        # print("BEFORE IFIT %i" % y)
        # print(self.learner.get_hset())
        self.learner.ifit(t, grounded, y)
        # print("AFTER IFIT")
        # print(self.learner.get_hset())


class SpecificToGeneral(BaseILP):

    def __init__(self, args=None, constraints=None, remove_attrs=None):
        self.pos = set()
        self.operator = None
        self.concept = Cobweb3Node()
        self.pos_concept = CobwebNode()
        self.neg_concept = CobwebNode()

        if remove_attrs is None:
            remove_attrs = ['value']
        self.remove_attrs = remove_attrs

    def num_pos(self):
        return self.pos_concept.count

    def num_neg(self):
        return self.neg_concept.count

    def __len__(self):
        return self.count

    # def __repr__(self):
    #     return repr(self.operator)

    def check_match(self, t, x):
        """
        if y is predicted to be 1 then returns True
        else returns False
        """
        # print("CHECK MATCHES T", t)
        x = x.get_view("flat_ungrounded")

        if self.operator is None:
            return

        t = tuple(ele.replace('?', "QM") for ele in t)

        mapping = {a: t[i] for i, a in enumerate(self.operator.name[1:])}

        # print("MY MAPPING", mapping)

        # print("CHECKING MATCHES")
        grounded = [(ground(a), x[a]) for a in x if (isinstance(a, tuple))]
        # pprint(grounded)
        # pprint(mapping)
        index = build_index(grounded)

        for m in self.operator.match(index, initial_mapping=mapping):
            return True
        return False

    def get_matches(self, x, constraints=None, epsilon=0.0):
        x = x.get_view("flat_ungrounded")

        if self.operator is None:
            return

        # print("GETTING MATCHES")
        grounded = [(ground(a), x[a]) for a in x if (isinstance(a, tuple))]
        # print("FACTS")
        # pprint(grounded)
        index = build_index(grounded)

        # print("INDEX")
        # pprint(index)

        # print("OPERATOR")
        # pprint(self.operator)

        for m in self.operator.match(index, epsilon=epsilon):
            # print('match', m, self.operator.name)
            result = tuple([unground(subst(m, ele))
                            for ele in self.operator.name[1:]])
            # result = tuple(['?' + subst(m, ele)
            #                 for ele in self.operator.name[1:]])
            # result = tuple(['?' + m[e] for e in self.target_types])
            # print('GET MATCHES T', result)
            yield result

        # print("GOT ALL THE MATCHES!")

        # for t in self.pos:
        #     print(t)
        #     yield t
        # X = {a: X[a] for a in X if not isinstance(a, tuple)
        #      or a[0] != 'value'}
        # pprint(X)
        # print('inferring match')
        # temp = self.tree.infer_missing(X)
        # print('done')

        # foas = []
        # for attr in temp:
        #     if isinstance(attr, tuple) and 'foa' in attr[0]:
        #         foas.append((float(attr[0][3:]), attr[1]))
        # foas.sort()
        # return tuple([e for _,e in foas])

    def matches(self, eles, attribute):
        for e in eles:
            if contains_component(e, attribute):
                return True
        return False

    def is_structural_feature(self, attr, value):
        if not isinstance(attr, tuple) or attr[0] != 'value':
            return True
        # print('REMOVING: ', attr, value)
        return False

    def ifit(self, t, x, y):
        x = x.get_view("flat_ungrounded")
        # print("IFIT T", t)
        # if y == 0:
        #     return

        x = {a: x[a] for a in x if (isinstance(a, tuple) and a[0] not in
                                    self.remove_attrs) or
                                   (not isinstance(a, tuple) and a not in
                                    self.remove_attrs)}
        # pprint(x)

        # x = {a: x[a] for a in x if self.is_structural_feature(a, x[a])}
        # x = {a: x[a] for a in x}

        # eles = set([field for field in t])
        # prior_count = 0
        # while len(eles) - prior_count > 0:
        #     prior_count = len(eles)
        #     for a in x:
        #         if isinstance(a, tuple) and a[0] == 'haselement':
        #             if a[2] in eles:
        #                 eles.add(a[1])
        #             # if self.matches(eles, a):
        #             #     names = get_attribute_components(a)
        #             #     eles.update(names)

        # x = {a: x[a] for a in x
        #      if self.matches(eles, a)}

        # foa_mapping = {field: 'foa%s' % j for j, field in enumerate(t)}
        foa_mapping = {}
        for j, field in enumerate(t):
            if field not in foa_mapping:
                foa_mapping[field] = 'foa%s' % j

        # print(foa_mapping)

        # for j,field in enumerate(t):
        #     x[('foa%s' % j, field)] = True
        x = rename_flat(x, foa_mapping)

        # print("adding:")

        ns = NameStandardizer()
        sm = StructureMapper(self.concept)
        x = sm.transform(ns.transform(x))

        pprint(x)
        # pprint(x)
        self.concept.increment_counts(x)

        if y > 0:
            self.pos_concept.increment_counts(x)
        else:
            self.neg_concept.increment_counts(x)

        print(self.pos_concept)

        # print()
        # print('POSITIVE')
        # pprint(self.pos_concept.av_counts)
        # print('NEGATIVE')
        # pprint(self.neg_concept.av_counts)

        # pprint(self.concept.av_counts)

        pos_instance = {}
        pos_args = set()
        for attr in self.pos_concept.av_counts:
            attr_count = 0
            for val in self.pos_concept.av_counts[attr]:
                attr_count += self.pos_concept.av_counts[attr][val]
            if attr_count == self.pos_concept.count:
                if len(self.pos_concept.av_counts[attr]) == 1:
                    args = get_vars(attr)
                    pos_args.update(args)
                    pos_instance[attr] = val
                else:
                    args = get_vars(attr)
                    val_gensym = value_gensym()
                    args.append(val_gensym)
                    pos_instance[attr] = val_gensym

        pprint(pos_instance)
        pprint(pos_args)
        print("av_counts")
        pprint(self.pos_concept.av_counts)

        # if len(self.pos_concept.av_counts[attr]) == 1:
        #     for val in self.pos_concept.av_counts[attr]:
        #         if ((self.pos_concept.av_counts[attr][val] ==
        #              self.pos_concept.count)):
        #             args = get_vars(attr)
        #             pos_args.update(args)
        #             pos_instance[attr] = val

        # print('POS ARGS', pos_args)

        neg_instance = {}
        for attr in self.neg_concept.av_counts:
            # print("ATTR", attr)
            args = set(get_vars(attr))
            if not args.issubset(pos_args):
                continue

            for val in self.neg_concept.av_counts[attr]:
                # print("VAL", val)
                if ((attr not in self.pos_concept.av_counts or val not in
                     self.pos_concept.av_counts[attr])):
                    neg_instance[attr] = val

        foa_mapping = {'foa%s' % j: '?foa%s' % j for j in range(len(t))}
        pos_instance = rename_flat(pos_instance, foa_mapping)
        neg_instance = rename_flat(neg_instance, foa_mapping)

        conditions = ([(a, pos_instance[a]) for a in pos_instance] +
                      [('not', (a, neg_instance[a])) for a in neg_instance])

        print(conditions)

        # print("========CONDITIONS======")
        # pprint(conditions)
        # print("========CONDITIONS======")

        self.target_types = ['?foa%s' % i for i in range(len(t))]
        self.operator = Operator(tuple(['Rule'] + self.target_types),
                                 conditions, [])
        print("_-----------------------------------")

    def fit(self, T, X, y):
        self.count = len(X)
        self.target_types = ['?foa%s' % i for i in range(len(T[0]))]

        # ignore X and save the positive T's.
        for i, t in enumerate(T):
            if y[i] == 1:
                self.pos.add(t)

        self.concept = Cobweb3Node()

        for i, t in enumerate(T):
            self.ifit(t, X[i], y[i])


def get_where_sublearner(name, **learner_kwargs):
    return WHERE_SUBLEARNERS[name.lower().replace(' ', '').replace('_', '')](**learner_kwargs)


def get_where_learner(name, learner_kwargs={}):
    return WhereLearner(name, learner_kwargs)





# if __name__ == "__main__":

    # ssw = RelationalLearner(args=('?foa0',),
    #                         constraints=frozenset([('name', '?foa0',
    #                                               '?foa0val')]))
    # ssw = SpecificToGeneral(args=('?foa0',),
    #                         constraints=frozenset([('name', '?foa0',
    #                                               '?foa0val')]))

    # ssw = MostSpecific(args=('?foa0',),
    #                         constraints=frozenset([('name', '?foa0',
    #                                               '?foa0val')]))
    # p1 = {('on', '?o1'): '?o2',
    #       ('name', '?o1'): "Block 1",
    #       ('name', '?o2'): "Block 7",
    #       ('valuea', '?o2'): 99}

    # p2 = {('on', '?o3'): '?o4',
    #       ('name', '?o3'): "Block 3",
    #       ('name', '?o4'): "Block 4",
    #       ('valuea', '?o4'): 2}

    # n1 = {('on', '?o5'): '?o6',
    #       ('on', '?o6'): '?o7',
    #       ('name', '?o5'): "Block 5",
    #       ('name', '?o6'): "Block 6",
    #       ('name', '?o7'): "Block 7",
    #       ('valuea', '?o7'): 100}

    # ssw.ifit(['?o1'], p1, 1)
    # ssw.ifit(['?o5'], n1, 0)
    # ssw.ifit(['?o3'], p2, 1)

    # test1 = {('on', '?o5'): '?o6',
    #          ('on', '?o6'): '?o7',
    #          ('name', '?o5'): "Block 1",
    #          ('name', '?o6'): "Block 7",
    #          ('name', '?o7'): "Block 5",
    #          ('valuea', '?o6'): 3}

    # print()
    # print("FINAL HYPOTHESIS")
    # print(ssw.learner.get_hset())

    # ms = SpecificToGeneral(args=('foa0','foa1'))#,
    #                         # constraints=frozenset([('name', '?foa0',
    #                         #                       '?foa0val')]))

    # state = {'columns' : { 
    #             "0": {
    #                 "0":{"?ele1": {"id": "ele1", "value":7}},
    #                 "1":{"?ele2": {"id": "ele2", "value":8}}
    #             },
    #             "1": {
    #                 "0":{"?ele3": {"id": "ele3", "value":7}},
    #                 "1":{"?ele4": {"id": "ele4", "value":8}}
    #             }
    #         }
    #      }
    # from concept_formation.preprocessor import Flattener
    # from pprint import pprint
    # fl = Flattener()
    # state = fl.transform(state)

    # pprint(state)

    # ms.ifit(['?ele1','?ele2'], state, 1)
    # ms.ifit(['?ele3','?ele4'], state, 1)
    # ms.ifit(['?ele1','?ele3'], state, 0)
    # # ms.ifit(['?o3'], state, 1)

    # for m in ms.get_matches(state):
    #    print('OP MATCH', m)

import torch
def mask_select(x, m):
    return x[m.nonzero().view(-1)]


class VersionSpace(BaseILP):
    def __init__(self, args=None, constraints=None, use_neg=False, propose_gens=True):
        self.pos_concepts = VersionSpaceILP()
        self.neg_concepts = VersionSpaceILP() if use_neg else None
        self.propose_gens = propose_gens
        self.constraints = constraints
        self.use_neg = use_neg
        self.elem_slices = None
        self.elem_types = None
        self.initialized = False
        self.pos_ok = False
        self.neg_ok = False

    def initialize(self, n):
        assert n >= 1, "not enough elements"
        self.num_elems = n
        self.enumerizer = Enumerizer(start_num=0,
                                     force_add=["<#ANY>",None,'?sel'] + ['?arg%d' % i for i in range(n-1)],
                                     remove_attrs=['value'])
        self.initialized = True

    def ifit(self, t, x, y):
        # print("I AM VERSIONSPACE")
        x = x.get_view("object")
        # print([x[t_name] for t_name in t])

        #Do this just so everything is in the map
        
        # x = rename_values(x,{ele:"sel" if i == 0 else ele:"arg%d" % i-1 for i,ele in enumerate(t)})
        assert False not in ["type" in x[t_name] for t_name in t], "All interface elements must have a type and a static set of attributes."

        if(not self.initialized):
            self.initialize(len(t))
            self.elem_types = [x[t_name]["type"] for t_name in t]
        assert len(t) == self.num_elems, "incorrect number of arguments for this rhs"

        def _rename_values(x):
            return rename_values(x, {ele: "?sel" if i == 0 else "?arg%d" % (i-1) for i, ele in enumerate(t)})

        instances = [_rename_values(x[t_name]) for t_name in t]
        vs_elems = self.enumerizer.transform(instances)
        #Do this just so everything is in the map
        self.enumerizer.transform({i:x for i,x in enumerate(x.keys())})
        self.enumerizer.transform(list(x.values()))

        # print("VS")
        # print(self.enumerizer.transform(list(x.values())))

        if(self.elem_slices == None):
            self.elem_slices = [0] + np.cumsum([len(vs_elem) for vs_elem in vs_elems]).tolist()
        # print(t)
        # print(self.enumerizer.attr_maps[0])
        # print(x.keys())
        # print("vs_elems:", vs_elems, t)
        # print("BEFORE: ",self.pos_concepts.spec_concepts)
        flat_vs_elems = list(itertools.chain(*vs_elems))
        self.pos_concepts.ifit(flat_vs_elems, y)
        self.pos_ok = self.pos_ok or y > 0
        if(self.use_neg):
            self.neg_concepts.ifit(flat_vs_elems, 0 if y > 0 else 1)
            self.neg_ok = self.neg_ok or y < 0

        # print("AFTER: ",self.pos_concepts.spec_concepts)

        # for i in range(self.num_elems):

        # self.positive_concepts.ifit()

    # def match_elem(self,t_name):
    def check_constraints(self,t,x):
        if(self.constraints is None):
            return True
        for i,part in enumerate(t):
            c = 0 if i == 0 else 1
            if(not self.constraints[c](x[part])):
                return False
        return True

    def check_match(self, t, x):
        if(not self.pos_ok):
            return False

        x = x.get_view("object")

        if(not self.check_constraints(t,x)):
            return False

        def _rename_values(x):
            return rename_values(x, {ele: "?sel" if i == 0 else "?arg%d" % (i-1) for i, ele in enumerate(t)})

        instances = [_rename_values(x[t_name]) for t_name in t]
        vs_elem = self.enumerizer.transform(instances)
        # print(torch.tensor(vs_elem).view(3, -1))
        if(self.use_neg):
            x = torch.tensor(vs_elem, dtype=torch.uint8).view(1, -1)
            ps, pg = self.pos_concepts.spec_concepts, self.pos_concepts.gen_concepts
            ns, ng = self.neg_concepts.spec_concepts, self.neg_concepts.gen_concepts
            ZERO = self.pos_concepts.ZERO
            spec_consistency = (((ps == ZERO)) | (ps == x)).all(dim=-1)
            gen_consistency = (((pg == ZERO)) | (pg == x)).all(dim=-1)

            out = spec_consistency.any() & gen_consistency.all()
            # print(self.enumerizer.attr_maps[0])
            # print(self.enumerizer.back_maps[0])
            # print(x)
            # print(self.enumerizer.back_maps[0][x.view(-1).tolist()[0]], self.enumerizer.back_maps[0][5])
            # print(ps)
            # print((((ps == ZERO)) | (ps == x)))

            if(self.neg_ok):
                neg_gen_consistency = ((ng == ZERO) | (ng == ps) | (ng != x)).all(dim=-1)
                neg_spec_consistency = ((ns == ZERO) | (ns == ps) | (ns != x)).all(dim=-1)
                out = out & neg_gen_consistency.any() & neg_spec_consistency.any()
            
            return out.item()
        else:
            return self.pos_concepts.check_match(vs_elem) > 0

    def get_matches(self, x):
        if(not self.pos_ok):
            return

        state = x.get_view("object")
        # assert False not in [for x in range(self.num_elems), \
        # "It is not the case that the enum for argX == X+2"
        # print(self.enumerizer.transform_values(["?sel","?arg0","?arg1"]))

        if(self.elem_slices == None):
            return
        # print(self.pos_concepts.spec_concepts)

        # Create a tensor which contains the enum values associated with the when parts
        #  i.e. "?sel", "?arg0", "?arg1" would probably map to 2, 3, 4
        where_part_vals = self.enumerizer.transform_values(
                          ["?sel"] + ['?arg%d' % i for i in range(self.num_elems-1)])
        where_part_vals = torch.tensor(where_part_vals,dtype=torch.uint8)

        # Make a tensor that has all of the enum values for the names of the elements/objects
        #  in the state in order that they appear
        elem_names_list = [key for key in state.keys()]
        elem_names = self.enumerizer.transform_values(elem_names_list)
        elem_names = torch.tensor(elem_names,dtype=torch.uint8)

        # Make a list that has all of the enumerized elements/objects
        elems_list = [val for val in state.values()]
        elems = self.enumerizer.transform(elems_list)
        # pprint(elems_list)

        # Make a list that has all of the enumerized elements/objects, but zeros in
        #  all of the slot for attributes which have elements names as values. 
        #  Only make this replacement if the element is of a type that we match to
        zero_map = {ele_name: 0 for ele_name,ele in state.items() 
                    if 'type' in ele and ele['type'] in self.elem_types}
        elems_scrubbed = self.enumerizer.transform(elems_list, zero_map)
        
        # Split up the concepts by the where parts that each slice selects on
        ps, pg = self.pos_concepts.spec_concepts, self.pos_concepts.gen_concepts
        
        s = self.elem_slices
        split_ps = [ps[:, s[i]:s[i+1]] for i in range(len(self.elem_slices)-1)]
        if(self.neg_ok):
            ns, ng = self.neg_concepts.spec_concepts, self.neg_concepts.gen_concepts
            split_ns = [ns[:, s[i]:s[i+1]] for i in range(len(self.elem_slices)-1)]
        else:
            split_ns = [None] * len(split_ps)

        # Initialize a bunch of containers that we will fill
        inds_by_type = {}
        candidates_by_type = {}
        scrubbed_by_type = {}
        elem_names_by_type = {}
        consistencies = []
        concept_cand_indicies = []
        concept_candidates = []
        concept_cand_replacements = []
        

        ZERO = self.pos_concepts.ZERO
        
        # Loop over the concepts for each where part and cull down the list of
        #   possible matches for them. This phase only filters out elements we can
        #   rule out without committing to any part of the where assignment. 
        for typ, ps_i, ns_i in zip(self.elem_types, split_ps, split_ns):

            # If the type for this concept is new then populate the list of candidates in various formats
            if(typ not in inds_by_type):
                candidate_indices = [i for i, e in enumerate(elem_names_list) if state[e]["type"] == typ]
                
                cnd = torch.tensor([elems[i] for i in candidate_indices], dtype=torch.uint8)
                candidates_by_type[typ] = cnd

                cnd_s = torch.tensor([elems_scrubbed[i] for i in candidate_indices], dtype=torch.uint8)
                cnd_s = cnd_s.view(len(candidate_indices), 1, ps_i.size(-1))
                scrubbed_by_type[typ] = cnd_s

                inds_by_type[typ] = torch.tensor(candidate_indices,dtype=torch.long)
                elem_names_by_type[typ] = torch.index_select(elem_names,0,inds_by_type[typ])
                
            else:
                candidate_indices = inds_by_type[typ]
                cnd_s = scrubbed_by_type[typ]

            # Check the consistency of each scrubbed candidate with the positive and negative
            #   concepts. This is a normal concept comparison except that any attribute slot where  
            #   the scrubbed candidate has a zero is always considered consistent. 
            ps_i = ps_i.unsqueeze(0)
            if(self.neg_ok):
                ns_i = ns_i.unsqueeze(0)


            consistency = ((ps_i == ZERO) | (ps_i == cnd_s) | (cnd_s == ZERO)).all(dim=-1).any(dim=-1)
            # print(consistency)
            if(self.neg_ok):
                ns_consistency = ((ns_i == ZERO) | (ns_i != cnd_s) | (ps_i == ns_i) | (cnd_s == ZERO)).all(dim=-1).any(dim=-1)
                consistency = consistency & ns_consistency

            #Store our culled down set of candidates in various formats
            consistencies.append(consistency)
            # print(ps_i)
            # print(consistency)
            # print(consistency)
            # print(self.enumerizer.back_maps[0])
            # print(ps_i)
            # print(((ps_i == ZERO) | (ps_i == cnd_s) | (cnd_s == ZERO)))
            # print(consistency.nonzero().tolist())

            # print([elem_names_list[j] for j in inds_by_type[typ].view(-1).tolist()])
            # print([self.enumerizer.back_maps[0][j] for j in elem_names_by_type[typ].view(-1).tolist()])
            # print()
            # print([elem_names_list[j] for j in torch.masked_select(inds_by_type[typ],consistency).tolist()])
            concept_cand_indicies.append(consistency.nonzero())
            concept_candidates.append( (consistency, torch.masked_select(elem_names_by_type[typ],consistency)) )

        # For each subset of the state of shape (N_t,d_t) consisting of all N_t, elements of type t
        #   with shared shape d_t, create a mask tensor of shape (n_w,N_t,d_t) such that each mask
        #   along its first dimension selects a different candidate assignment to 'where' part w.
        # print()
        replacements_by_type = {}
        for typ, cnd in candidates_by_type.items():
            # print(cnd)
            repls = []
            for consistency, elem_names in concept_candidates:
                repl = (cnd.unsqueeze(0) == elem_names.view(-1,1,1))
                repls.append(repl)
            replacements_by_type[typ] = repls

        # concept_repl_cons = []


        # Here we loop over the concepts for every where part and try every possible replacement 
        #   of element name enums with the enums for "?sel", "?arg0", "?arg1", etc to see if 
        #   the replacement is consistent with that concept.
        tot = None
        for i, (typ, ps_i, ns_i) in enumerate(zip(self.elem_types, split_ps, split_ns)):
            # cnd = candidates_by_type[typ]
            repls = replacements_by_type[typ]

            ps_i = ps_i.unsqueeze(0)
            if(self.neg_ok):
                ns_i = ns_i.unsqueeze(0)

            ok_i = None

            # concept_repl_cons.append([])

            # For each where part j check all assignments among the candidate elements
            #   for consistency with concept(i).   
            for j, repl in enumerate(repls):
                repl = repl.unsqueeze(-2)
                v = where_part_vals[j]

                # Calculate the tensor repl_consistency of shape (n_w, N_t) which has value 1 
                #   at element (r,e) if element e is consistent with concept set i given that 
                #   where part j was assigned to element r.  
                consistent = ps_consistency = ( (ps_i == v)).unsqueeze(0)
                if(self.neg_ok):
                    ns_consistency = ( (ns_i != v) | (ps_i == ns_i)).unsqueeze(0)
                    consistent = (ps_consistency & ns_consistency)

                # Element e is consistent with replacement r if the replacement changes the
                #   element so that all attributes for which the positive concept requires value v
                #   are replaced with value v, and no attributes are replaced with value v if it would
                #   make e match the negative concept.
                repl_consistency = ( ( (~ps_consistency) |  (repl & consistent) )).all(dim=-1).any(dim=-1)

                # If 'where' part j corresponds with concept i then we need to add the constraint that 
                #   our choice of the element for part j is the only possible consistent element with
                #   concept i. We can bitwise AND a diagonal matrix of shape (n_i,N_t) that has value 1 where the candidates
                #   for where part i align with the candidates from the original state to apply this constraint.
                if(i == j):
                    concept_diag = concept_cand_indicies[i].view(-1,1) == torch.arange(repl_consistency.size(-1)).view(1,-1)
                    repl_consistency = repl_consistency & concept_diag
                    
                # Broadcast repl_consistency and bitwise AND it with the repl_consistencies so far
                #   to ultimately create a tensor ok_i of shape (n_w1,n_w2,n_w3, ..., N_t) that contains a mask of 
                #   elements for each combination of where assignments which are which are mutually consistent 
                #   with concept set i. 
                repl_consistency = repl_consistency.view(*([1]*j + [-1] + (self.num_elems-(j+1))*[1] + [repl_consistency.size(-1)]))
                ok_i = (ok_i & repl_consistency) if ok_i is not None else repl_consistency
                

            ok_i = ok_i.any(dim=-1)

            # Bitwise AND all possible 'where' assignments for each concept to get a tensor of shape 
            #   (n_w1,n_w2,n_w3, ...,) that has value 1 only for 'where' assignments consistent with all concepts.
            tot = (tot & ok_i) if tot is not None else ok_i

        # Get the indicies of the consistent 'where' assignments 
        matches = tot.nonzero()
        # print(matches)

        # Translate these indicies so that they select from the original state
        translated = []
        for i,(typ,indicies) in enumerate(zip(self.elem_types,concept_cand_indicies)):
            rel_to_type = torch.index_select(indicies,0,matches[:,i])
            # print(rel_to_type)
            # print(inds_by_type[typ])
            # print(torch.index_select(inds_by_type[typ],0,rel_to_type.view(-1)))
            translated.append(torch.index_select(inds_by_type[typ],0,rel_to_type.view(-1)).view(-1,1))
        translated = torch.cat(translated,dim=1)
        # print(translated)
        
        #Yield each consistent 'where' assignments (i.e. the set of matches) by their original names
        for out_inds in translated.tolist():
            out = [elem_names_list[y] for y in out_inds]
            # print(out_inds)
            
            # print(out,self.check_constraints(out,state))
            # print([state[x].get('value',None) for x in out])
            if(self.check_constraints(out,state)):
                yield out

    def skill_info(self):
        out = {}
        
        s = self.elem_slices

        ps, pg = self.pos_concepts.spec_concepts, self.pos_concepts.gen_concepts
        split_ps = [ps[:, s[i]:s[i+1]] for i in range(len(self.elem_slices)-1)]
        if(self.neg_ok):
            ns, ng = self.neg_concepts.spec_concepts, self.neg_concepts.gen_concepts
            split_ns = [ns[:, s[i]:s[i+1]] for i in range(len(self.elem_slices)-1)]

        for i, t in enumerate(self.elem_types):
            key = "?sel" if i==0 else "?arg%d" % (i-1)
            out[key] = {}
            out[key]["pos"] = self.enumerizer.undo_transform(split_ps[i].tolist()[0],t)
            if(self.neg_ok):
                out[key]["neg"] = self.enumerizer.undo_transform(split_ns[i].tolist()[0],t)

        return out
            



class VersionSpaceILP(object):
    def __init__(self):
        self.spec_concepts = None
        self.gen_concepts = None
        self.ZERO = None
        self.unused_concepts = []

    def ifit(self, x, y):
        # print(x)
        # print(x)
        x = torch.tensor(x, dtype=torch.uint8).view(1, -1)
        # print("x", y)
        # print(x)
        clen = self.clen = x.shape[-1]
        if(y > 0):
            if(isinstance(self.spec_concepts, type(None))):
                self.spec_concepts = x
                self.gen_concepts = torch.zeros(x.shape, dtype=torch.uint8)
                self.ZERO = torch.tensor(0, dtype=torch.uint8)
                for _x, _y in self.unused_concepts:
                    self.ifit(_x, _y)
                self.unused_concepts = None
            else:
                # Generalize the specific concepts to incorperate the positive example
                self.spec_concepts = torch.where(x != self.spec_concepts, self.ZERO, self.spec_concepts)

                # Prune the general concepts that are inconsistent with the positive example
                gen_consistency = (self.gen_concepts == self.ZERO) | (self.gen_concepts == x)
                self.gen_concepts = mask_select(self.gen_concepts, gen_consistency.all(dim=1))

        else:
            if(isinstance(self.spec_concepts, type(None))):
                self.unused_concepts.append((x, y))
                return
            else:
                # ### Start: Make the General Concepts more specific ####
                spec_inconsistency = ~((self.spec_concepts == self.ZERO) | (self.spec_concepts == x))
                gen_consistency = (self.gen_concepts == self.ZERO) | (self.gen_concepts == x)

                # The set of general concepts which are contain the negative example and must be specialized 
                to_specilz_concepts = mask_select(self.gen_concepts, gen_consistency.all(dim=1))
                # The set of general concepts which do not contain the negative example an so we leave alone
                to_keep_concepts = mask_select(self.gen_concepts, (~gen_consistency).any(dim=1))

                # The set of concepts with only one specific element which are present in
                # the most specific concept but not this negative example.
                specialization_candidates = torch.eye(clen, dtype=torch.uint8).view(1, clen, clen)*(spec_inconsistency*self.spec_concepts).view(-1, 1, clen)
                specialization_candidates = mask_select(specialization_candidates.view(-1, clen), spec_inconsistency.view(-1))

                # Specialize each concept (among those we found earlier that contain the negative example)
                #   creating all new possible general concepts for each element which is still general
                sc, tsc, = specialization_candidates.view(1, -1, clen), to_specilz_concepts.view(-1, 1, clen)
                possible_specialized_gens = torch.where((tsc == self.ZERO), sc, tsc).view(-1, clen)
                # specialized_gens = torch.where((tsc == self.ZERO) & gen_consistency.view(1,-1,clen), sc,tsc).view(-1,clen)

                # If a possible specialization is consistent with the non-specialized general concepts then keep it
                new_gen_consistency = (to_keep_concepts.view(1, -1, clen) == self.ZERO) | (to_keep_concepts.view(1, -1, clen) == possible_specialized_gens.view(-1, 1, clen))
                inconsistent_w_keepers = (~new_gen_consistency).any(dim=-1).all(dim=-1)
                specialized_gens = mask_select(possible_specialized_gens, inconsistent_w_keepers)

                # Join the tensors of non-specialized and specialized concepts
                self.gen_concepts = torch.cat([to_keep_concepts, specialized_gens], dim=0)

                # ### Start: Prune Specific Concepts ####
                # TODO: Never happens? What does it look like if we allow for multiple specific concepts?
                # self.spec_concepts = mask_select(self.spec_concepts, spec_inconsistency.any(dim=1))

        # print("GENERAL")
        # print(self.gen_concepts)
        # print("SPECIFIC")
        # print(self.spec_concepts, self.spec_concepts.shape)

        # print("---------------------------------")

    def check_match(self, x):
        '''Returns true if x is consistent with all general concepts and any specific concept'''
        x = torch.tensor(x, dtype=torch.uint8).view(1, -1)
        spec_consistency = ((self.spec_concepts == self.ZERO) | (self.spec_concepts == x)).all(dim=-1)
        gen_consistency = ((self.gen_concepts == self.ZERO) | (self.gen_concepts == x)).all(dim=-1)
        return (spec_consistency.any() & gen_consistency.all()).item()


def rename_values(x, mapping, rename_keys=False): 
    if(isinstance(x, dict)):
        if(rename_keys):
            return {rename_values(name, mapping): rename_values(val, mapping) for name, val in x.items()}
        else:
            return {name: rename_values(val, mapping) for name, val in x.items()}
    elif(isinstance(x, list)):
        return [rename_values(val, mapping) for val in x]
    elif(isinstance(x, tuple)):
        return tuple([rename_values(val, mapping) for val in x])
    elif(x in mapping):
        return mapping[x]
    else:
        return x

from concept_formation.preprocessor import Preprocessor
class Enumerizer(Preprocessor):
    def __init__(self, start_num=0, force_add=[],attrs_independant=False,remove_attrs=[]):
        self.start_num = start_num
        self.attr_maps = {}
        self.force_add = force_add
        self.attrs_independant = attrs_independant
        self.type_lengths = {}
        self.remove_attrs = remove_attrs
        # self.attr_counts = {}
        self.back_maps = {}
        self.back_keys = {}
        self.keys = []

    def transform_values(self,values):
        assert not self.attrs_independant, \
            "attrs_independant, must be false. Mapping ambiguous."
        mapping = self.attr_maps[0]
        return [mapping[x] for x in values]

    '''Maps nominals to unsigned integers'''
    #TODO: MAKE IT ASSERT A FIXED REPRESENTATION SOMEHOW
    def transform(self, instances, force_map=None):
        """
        Transforms an instance.
        """
        if(isinstance(instances, dict)):
            instances = [instances]

        def instance_iter(instance):
            for key,value in instance.items():
                if(isinstance(value,(list,tuple))):
                    for i,v in enumerate(value):
                        yield (key,i), v
                else:
                    yield key,value
        
        # print(instances)
        enumerized_instances = []
        for i, instance in enumerate(instances):

            if("type" in instance):
                back_keys = self.back_keys[instance['type']] = [] 
            else:
                back_keys = None

            enumerized_instance = []
            for j,(k, value) in enumerate(instance_iter(instance)):
                # print(instance,k)
                if(k in self.remove_attrs):
                    continue

                if(back_keys is not None and j >= len(back_keys)):
                    back_keys.append(k)
                # print(value)
                if(force_map != None and value in force_map):
                    enumerized_instance.append(force_map[value])
                else:
                    key = (instance["type"],k) if self.attrs_independant else 0
                    if(key not in self.attr_maps):
                        # if(fail_on_grow):
                        #     raise ValueError("Dynamic")
                        self.attr_maps[key] = {x: i+self.start_num for i, x in enumerate(self.force_add)}
                        # self.attr_counts[key] = self.start_num
                        self.back_maps[key] = [None for i in range(self.start_num)] + self.force_add
                        self.keys.append(key)
                    attr_map = self.attr_maps[key]
                    if(value not in attr_map):
                        attr_map[value] = len(self.back_maps[key])
                        self.back_maps[key].append(value)
                        # self.attr_counts[key] += 1
                    enumerized_instance.append(attr_map[value])
            # print()
            if("type" in instance):
                inst_type = instance['type']
                if(inst_type in self.type_lengths):
                    assert self.type_lengths[inst_type] == len(enumerized_instance), \
                    "Got type %s with number of attributes %s (should be %s)" % \
                    (inst_type,len(enumerized_instance),self.type_lengths[inst_type])
                else:
                    self.type_lengths[inst_type] = len(enumerized_instance)

            enumerized_instances.append(enumerized_instance)
        return enumerized_instances

    def undo_transform(self, instance,typ):
        """
        Undoes a transformation to an instance.
        """
        

        d = {}

        if(self.attrs_independant):
            assert len(instance) == len(self.keys)
            for enum, key in zip(instance, self.keys):
                d[key] = self.back_maps[key][enum]
        else:
            # for key in self.back_maps[0]:
            #     print(key)
            # print("---------------------")
            back_map = self.back_maps[0]
            back_keys = self.back_keys[typ]
            # print(self.back_keys)
            # print(back_keys)
            # list_keys = {}
            for i,key in enumerate(back_keys):
                # print(back_keys[instance[i]])
                if(isinstance(key,tuple)):
                    lst = d.get(key[0],[None]*(key[1]+1))
                    if(len(lst) <= key[1]):
                        lst += [None]*(key[1]+1-len(lst))
                    # print(lst,key[1])
                    lst[key[1]] = back_map[instance[i]]
                    d[key[0]] = lst
                else:
                    d[key] = back_map[instance[i]]


        return d

# def version_space():

WHERE_SUBLEARNERS = {
    'versionspace': VersionSpace,
    'mostspecific': MostSpecific,
    'stateresponselearner': StateResponseLearner,
    'relationallearner': RelationalLearner,
    'specifictogeneral': SpecificToGeneral
}

WHERE_STRATEGY = {
    'versionspace': "object",
    'mostspecific': "first_order",
    'stateresponselearner': "first_order",
    'relationallearner': "first_order",
    'specifictogeneral': "first_order"   
}


if __name__ == "__main__":
    vthang = VersionSpaceILP()

    vthang.ifit([1,1,1,2,1],1)
    vthang.ifit([1,2,2,1,2],0)
    vthang.ifit([1,2,1,3,1],1)
    vthang.ifit([2,3,3,2,1],0)
    vthang.ifit([1,1,4,2,1],1)
    print(vthang.check_match([1,1,1,2,1]))
    print(vthang.check_match([1,2,2,1,2]))

    vthang = VersionSpaceILP()

    print("@@@@@@@")
    vthang.ifit([1,2,2,1],1)
    vthang.ifit([2,2,2,1],0)
    vthang.ifit([1,2,2,2],1)
    vthang.ifit([2,2,2,2],0)
    vthang.ifit([1,2,1,2],1)
    vthang.ifit([2,2,1,2],0)
    vthang.ifit([1,1,1,1],0)
    vthang.ifit([1,1,2,1],0)
    vthang.ifit([1,1,2,2],0)
    vthang.ifit([1,1,1,2],0)

    # vthang.ifit([1,1,1,1,1,1,1],1)
    # vthang.ifit([1,0,0,0,1,1,1],1)
    # vthang.ifit([1,1,1,0,0,0,1],1)
    # vthang.ifit([1,1,1,0,0,0,0],0)

    state = {
        "line" : {
            "type" : "bloop",
            # 'value': "-",
            "above": ["B1","A1"],
            "below": ["C1",None],
            "left" : None,
            "right": None,
        },
        "A1": {
            "type" : "text",
            "value": 1,
            "above": [None,None],
            "below": ["B1","C1"],
            "left" : "A2",
            "right": None,
        },
        "A2": {
            "type" : "text",
            "value": 2,
            "above": [None,None],
            "below": ["B2","C2"],
            "left" : "A3",
            "right": "A1",
        },
        "A3": {
            "type" : "text",
            "value": 3,
            "above": [None,None],
            "below": ["B3","C3"],
            "left" : None,
            "right": "A2",
        },
        "B1": {
            "type" : "text",
            "value": 4,
            "above": ["A1", None],
            "below": ["line","C1"],
            "left" : "B2",
            "right": None,
        },
        "B2": {
            "type" : "text",
            "value": 5,
            "above": ["A2", None],
            "below": ["line","C2"],
            "left" : "B3",
            "right": "B1",
        },
        "B3": {
            "type" : "text",
            "value": 6,
            "above": ["A3", None],
            "below": ["line","C3"],
            "left" : None,
            "right": "B2",
        },
        "C1": {
            "type" : "text",
            "value": 7,
            "above": ["line","B1"],
            "below": [None,None],
            "left" : "C2",
            "right": None,
        },
        "C2": {
            "type" : "text",
            "value": 8,
            "above": ["line","B2"],
            "below": [None,None],
            "left" : "C1",
            "right": "C3",
        },
        "C3": {
            "type" : "text",
            "value": 9,
            "above": ["line","B3"],
            "below": [None,None],
            "left" : None,
            "right": "C2",
        }
    }
    from agents.ModularAgent import StateMultiView
    state = StateMultiView("object",state)

    # enumer = Enumerizer(start_num=1, force_add=[None])

    # Av = VersionSpaceILP()
    # Bv = VersionSpaceILP()

    # inv = [(k, e) for k, e in state.items()][::-1]
    # for key, ele in inv:
    #     # for key,ele in state.items():
    #     ele_tensor = enumer.transform(ele)
    #     print("G", ele_tensor)
    #     if("A" in key):
    #         # Av.ifit(ele_tensor,1)
    #         Bv.ifit(ele_tensor, 0)
    #     elif("B" in key):
    #         # Av.ifit(ele_tensor,0)
    #         Bv.ifit(ele_tensor, 1)

    vs = VersionSpace(use_neg=True)
    vs.ifit(["C1","A1","B1"],state,1)
    
    vs.ifit(["C1","B1","A1"],state,0)
    for match in vs.get_matches(state):
        print(match)
    vs.ifit(["C2","A2","B2"],state,1)
    for match in vs.get_matches(state):
        print(match)
    vs.ifit(["C1","B2","A2"],state,0)
    # vs.ifit(["C3","A3","B3"],state,1)
    vs.ifit(["C3","A3","A2"],state,0)

    print(vs.check_match(["C1","A1","B1"],state), 1)
    print(vs.check_match(["C1","B1","A1"],state), 0)
    print(vs.check_match(["C2","A2","B2"],state), 1)
    print(vs.check_match(["C1","B2","A2"],state), 0)
    print(vs.check_match(["C3","A3","B3"],state), 1)
    print(vs.check_match(["C3","A3","A2"],state), 0)
    print(vs.check_match(["C3","A1","A3"],state), 0)
    print(vs.check_match(["A2","A3","B3"],state), 0)
    print(vs.check_match(["C1","A3","C3"],state), 0)
    print(vs.check_match(["C1","A2","B2"],state), 0)
    print(vs.check_match(["C1","B2","B1"],state), 0)
    print(vs.check_match(['C1','A1','B3'],state), 0)
    print(vs.check_match(['B1','A2','B2'],state), 0)

    print(rename_values(state,{"C1": "sel", "A1" : "arg0", "B1": "arg1"},False))
    for match in vs.get_matches(state):
        print(match)

    # pprint._
    pprint(vs.skill_info())
    # print(vs.enumerizer.undo_transform(vs.pos_concepts.spec_concepts.tolist()[0]))
    # print(vs.enumerizer.undo_transform(vs.pos_concepts.spec_concepts.tolist()[1]))
    # print(vs.enumerizer.undo_transform(vs.pos_concepts.spec_concepts.tolist()[2]))
    # print()
    # print(vs.pos_concepts.spec_concepts.view(3,-1))
    # print(vs.pos_concepts.gen_concepts.view(3,-1))
    # print(vs.neg_concepts.spec_concepts.view(3,-1))
    # print(vs.neg_concepts.gen_concepts.view(3,3,-1))
    # print()
    # print()
    # pprint(enumer.batch_undo(enumer.batch_transform(state.values())))
