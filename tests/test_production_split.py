# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
import unittest
from decimal import Decimal

import trytond.tests.test_tryton
from trytond.tests.test_tryton import ModuleTestCase, with_transaction
from trytond.pool import Pool

from trytond.modules.company.tests import create_company, set_company


class ProductionSplitTestCase(ModuleTestCase):
    'Test production_split module'
    module = 'production_split'

    @with_transaction()
    def test0010split(self):
        'Test split production'
        pool = Pool()
        Uom = pool.get('product.uom')
        Template = pool.get('product.template')
        Product = pool.get('product.product')
        Production = pool.get('production')
        Bom = pool.get('production.bom')
        Location = pool.get('stock.location')
        Inventory = pool.get('stock.inventory')

        # Create Company
        company = create_company()
        with set_company(company):
            input_, = Location.search([('code', '=', 'IN')])
            storage, = Location.search([('code', '=', 'STO')])
            production_loc, = Location.search([('code', '=', 'PROD')])
            warehouse, = Location.search([('code', '=', 'WH')])
            warehouse.production_location = production_loc
            warehouse.save()
            unit, = Uom.search([('name', '=', 'Unit')])
            template, = Template.create([{
                        'name': 'Product',
                        'type': 'goods',
                        'cost_price_method': 'fixed',
                        'default_uom': unit.id,
                        'list_price': Decimal(5),
                        'cost_price': Decimal(1),
                        }])
            product, = Product.create([{
                        'template': template.id,
                        }])
            template1, = Template.create([{
                        'name': 'Component 1',
                        'type': 'goods',
                        'cost_price_method': 'fixed',
                        'default_uom': unit.id,
                        'list_price': Decimal(5),
                        'cost_price': Decimal(1),
                        }])
            component1, = Product.create([{
                        'template': template1.id,
                        }])
            template2, = Template.create([{
                        'name': 'Component 2',
                        'type': 'goods',
                        'cost_price_method': 'fixed',
                        'default_uom': unit.id,
                        'list_price': Decimal(5),
                        'cost_price': Decimal(2),
                        }])
            component2, = Product.create([{
                        'template': template2.id,
                        }])

            bom, = Bom.create([{
                        'name': 'Product',
                        'inputs': [('create', [{
                                        'product': component1.id,
                                        'quantity': 5.0,
                                        'uom': unit.id,
                                        }, {
                                        'product': component2.id,
                                        'quantity': 2.0,
                                        'uom': unit.id,
                                        }])],
                        'outputs': [('create', [{
                                        'product': product.id,
                                        'quantity': 1.0,
                                        'uom': unit.id,
                                        }])],
                        }])

            def create_production(quantity):
                production, = Production.create([{
                            'product': product.id,
                            'bom': bom.id,
                            'uom': unit.id,
                            'quantity': quantity,
                            'warehouse': warehouse.id,
                            'location': production_loc.id,
                            'company': company.id,
                            }])
                production.set_moves()
                return production

            production = create_production(10)
            self.assertEqual(production.number, '1')
            productions = production.split(5, unit)
            self.assertEqual(len(productions), 2)
            self.assertEqual([p.number for p in productions], ['1-1', '1-2'])
            self.assertEqual([m.quantity for m in productions], [5, 5])
            self.assertEqual([sorted([m.quantity for m in p.inputs]) for p in
                    productions], [[10, 25], [10, 25]])
            self.assertEqual([[m.quantity for m in p.outputs] for p in
                    productions], [[5], [5]])

            production = create_production(13)
            productions = production.split(5, unit)
            self.assertEqual(len(productions), 3)
            self.assertEqual([m.quantity for m in productions], [5, 5, 3])
            self.assertEqual([sorted([m.quantity for m in p.inputs]) for p in
                    productions], [[10, 25], [10, 25], [6, 15]])
            self.assertEqual([[m.quantity for m in p.outputs] for p in
                    productions], [[5], [5], [3]])

            production = create_production(7)
            productions = production.split(8, unit)
            self.assertEqual(productions, [production])
            self.assertEqual(production.quantity, 7)
            self.assertEqual(sorted([m.quantity for m in production.inputs]),
                [14, 35])
            self.assertEqual([m.quantity for m in production.outputs], [7])

            production = create_production(20)
            productions = production.split(5, unit, count=2)
            self.assertEqual(len(productions), 3)
            self.assertEqual([m.quantity for m in productions], [5, 5, 10])
            self.assertEqual([sorted([m.quantity for m in p.inputs]) for p in
                    productions], [[10, 25], [10, 25], [20, 50]])
            self.assertEqual([[m.quantity for m in p.outputs] for p in
                    productions], [[5], [5], [10]])

            production = create_production(20)
            productions = production.split(5, unit, count=4)
            self.assertEqual(len(productions), 4)
            self.assertEqual([m.quantity for m in productions], [5, 5, 5, 5])
            self.assertEqual([sorted([m.quantity for m in p.inputs]) for p in
                    productions], [[10, 25], [10, 25], [10, 25], [10, 25]])
            self.assertEqual([[m.quantity for m in p.outputs] for p in
                    productions], [[5], [5], [5], [5]])

            production = create_production(10)
            productions = production.split(5, unit, count=3)
            self.assertEqual(len(productions), 2)
            self.assertEqual([m.quantity for m in productions], [5, 5])
            self.assertEqual([sorted([m.quantity for m in p.inputs]) for p in
                    productions], [[10, 25], [10, 25]])
            self.assertEqual([[m.quantity for m in p.outputs] for p in
                    productions], [[5], [5]])

            production = create_production(10)
            Production.wait([production])
            productions = production.split(5, unit)
            self.assertEqual(len(productions), 2)
            self.assertEqual([m.quantity for m in productions], [5, 5])
            self.assertEqual([m.state for m in productions],
                ['waiting', 'waiting'])

            inventory, = Inventory.create([{
                        'company': company.id,
                        'location': storage.id,
                        'lines': [('create', [{
                                        'product': component1.id,
                                        'quantity': 50,
                                        }, {
                                        'product': component2.id,
                                        'quantity': 20,
                                        }])],
                        }])
            Inventory.confirm([inventory])

            production = create_production(10)
            Production.wait([production])
            self.assertEqual(Production.assign_try([production]), True)
            productions = production.split(5, unit)
            self.assertEqual(len(productions), 2)
            self.assertEqual([m.quantity for m in productions], [5, 5])
            self.assertEqual([m.state for m in productions],
                ['assigned', 'assigned'])
            self.assertEqual([sorted([m.quantity for m in p.inputs]) for p in
                    productions], [[10, 25], [10, 25]])
            self.assertEqual([[m.quantity for m in p.outputs] for p in
                    productions], [[5], [5]])
            self.assertEqual(all([m.state == 'draft' for m in p.outputs
                        for p in productions]), True)

            production = create_production(10)
            production.bom == None
            production.product == None
            production.save()
            productions = production.split(5, unit)
            self.assertEqual(len(productions), 2)
            self.assertEqual([sorted([m.quantity for m in p.inputs]) for p in
                    productions], [[10, 25], [10, 25]])
            self.assertEqual([[m.quantity for m in p.outputs] for p in
                    productions], [[5], [5]])
            production = create_production(10)
            production.product == None
            production.save()

            production = create_production(10)
            Production.write([production], {
                    'bom': None,
                    'outputs': [('create', [{
                                    'product': component2.id,
                                    'uom': unit.id,
                                    'quantity': 2,
                                    'from_location': production_loc.id,
                                    'to_location': storage.id,
                                    'company': company.id,
                                    'currency': company.currency.id,
                                    'unit_price': component2.cost_price,
                                    },
                                ])]
                    })
            self.assertEqual(len(production.outputs), 2)
            productions = production.split(5, unit)
            self.assertEqual(len(productions), 2)
            self.assertEqual([sorted([m.quantity for m in p.inputs]) for p in
                    productions], [[10, 25], [10, 25]])
            self.assertEqual([sorted([m.quantity for m in p.outputs]) for p in
                    productions], [[1, 5], [1, 5]])


def suite():
    suite = trytond.tests.test_tryton.suite()
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(
            ProductionSplitTestCase))
    return suite
