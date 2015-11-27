#This file is part of Tryton.  The COPYRIGHT file at the top level of
#this repository contains the full copyright notices and license terms.
from trytond.model import ModelView, fields
from trytond.wizard import Wizard, StateView, StateTransition, Button
from trytond.pyson import Eval
from trytond.pool import Pool, PoolMeta
from trytond.transaction import Transaction

__all__ = ['Production', 'SplitProductionStart', 'SplitProduction']
__metaclass__ = PoolMeta


class Production:
    __name__ = 'production'

    @classmethod
    def __setup__(cls):
        super(Production, cls).__setup__()
        cls._buttons.update({
                'split_wizard': {
                    'readonly': ~Eval('state').in_(['request', 'draft',
                            'waiting', 'assigned']),
                    },
                })

    @classmethod
    @ModelView.button_action('production_split.wizard_split_production')
    def split_wizard(cls, productions):
        pass

    def split(self, quantity, uom, count=None):
        """
        Split the production into productions of quantity.
        If count is not defined, the production will be split until the
        remainder is less than quantity.
        Return the splitted productions
        """
        pool = Pool()
        Uom = pool.get('product.uom')

        initial = remainder = Uom.compute_qty(self.uom, self.quantity, uom)
        factor = quantity / initial
        productions = [self]
        if remainder <= quantity:
            return productions
        state = self.state
        code = self.code
        self.write([self], {
                'state': 'draft',
                'quantity': quantity,
                'uom': uom.id,
                'code': '%s-%s' % (code, 1)
                })
        remainder -= quantity
        if count:
            count -= 1
        suffix = 2
        while (remainder > quantity
                and (count or count is None)):
            productions.append(self._split_production(factor, quantity, uom,
                    '%s-%s' % (code, suffix)))
            remainder -= quantity
            if count:
                count -= 1
            suffix += 1
        assert remainder >= 0
        if remainder:
            productions.append(self._split_production(remainder / initial,
                    remainder, uom, '%s-%s' % (code, suffix)))
        self._split_inputs_outputs(factor)
        self.write(productions, {
                'state': state,
                })
        return productions

    def _split_production(self, factor, quantity, uom, code):
        with Transaction().set_context(preserve_moves_state=True):
            production, = self.copy([self], {
                    'quantity': quantity,
                    'uom': uom.id,
                    'code': code,
                    })
        production._split_inputs_outputs(factor)
        return production

    def _split_inputs_outputs(self, factor):
        pool = Pool()
        Move = pool.get('stock.move')
        moves = list(self.inputs + self.outputs)
        reset_state, to_write = [], []
        for input_ in self.inputs:
            state = input_.state
            to_write.extend(([input_], {
                        'quantity': input_.uom.round(input_.quantity * factor,
                            input_.uom.rounding),
                        }))
            if state != 'draft':
                reset_state.extend(([input_], {'state': state}))
        for output in self.outputs:
            to_write.extend(([output], {
                        'quantity': output.uom.round(output.quantity * factor,
                            output.uom.rounding),
                        }))
        Move.write(moves, {'state': 'draft'})
        if to_write:
            Move.write(*to_write)
        if reset_state:
            Move.write(*reset_state)


class SplitProductionStart(ModelView):
    'Split Production'
    __name__ = 'production.split.start'
    count = fields.Integer('Count', help='Maximum number of productions to'
        ' create')
    quantity = fields.Float('Quantity', required=True,
        digits=(16, Eval('unit_digits', 2)),
        depends=['unit_digits'])
    uom = fields.Many2One('product.uom', 'Uom', required=True,
        domain=[
            ('category', '=', Eval('uom_category')),
            ],
        depends=['uom_category'])
    unit_digits = fields.Integer('Unit Digits', readonly=True)
    uom_category = fields.Many2One('product.uom.category', 'Uom Category',
        readonly=True)

    @fields.depends('uom')
    def on_change_with_unit_digits(self):
        if self.uom:
            return self.uom.digits
        return 2


class SplitProduction(Wizard):
    'Split Production'
    __name__ = 'production.split'
    start = StateView('production.split.start',
        'production_split.split_start_view_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Split', 'split', 'tryton-ok', default=True),
            ])
    split = StateTransition()

    @classmethod
    def __setup__(cls):
        super(SplitProduction, cls).__setup__()
        cls._error_messages.update({
                'no_product_nor_quantity': ('Production "%s" must have product'
                    ' and quantity defined in order to be splited.')
                })

    def default_start(self, fields):
        pool = Pool()
        Production = pool.get('production')
        default = {}
        production = Production(Transaction().context['active_id'])
        if not production.product or not production.quantity:
            self.raise_user_error('no_product_nor_quantity',
                production.rec_name)
        if production.uom:
            default['uom'] = production.uom.id
            default['unit_digits'] = production.unit_digits
            default['uom_category'] = production.uom.category.id
        return default

    def transition_split(self):
        pool = Pool()
        Production = pool.get('production')
        production = Production(Transaction().context['active_id'])
        production.split(self.start.quantity, self.start.uom, self.start.count)
        return 'end'
