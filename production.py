# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
from trytond.model import ModelView, fields
from trytond.wizard import Wizard, StateView, StateTransition, Button
from trytond.pyson import Eval
from trytond.pool import Pool, PoolMeta
from trytond.transaction import Transaction
from trytond.i18n import gettext
from trytond.exceptions import UserError

__all__ = ['Production', 'SplitProductionStart', 'SplitProduction']


class Production(metaclass=PoolMeta):
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
        Return the splitted productions.
        The current production (self) will have the "remaining" quantities.

        If the initial production has more than one input for the same product,
        it will try to don't split these moves if it's not necessary.
        """
        pool = Pool()
        Uom = pool.get('product.uom')

        initial = remainder = Uom.compute_qty(self.uom, self.quantity, uom)
        if remainder <= quantity:
            # Splitted to quantity greater than produciton's quantity
            return [self]

        factor = quantity / initial
        input2qty = {}  # amount for each input in splitted productions
        for input_ in self.inputs:
            # Maybe someone want customize the key of the dictionary
            input2qty.setdefault(input_.product.id, 0)
            input2qty[input_.product.id] += Uom.compute_qty(
                input_.uom, input_.quantity * factor,
                input_.product.default_uom,
                round=False)
        output2qty = {}  # amount for each output in splitted productions
        for output in self.outputs:
            # Maybe someone want customize the key of the dictionary
            output2qty.setdefault(output.product.id, 0)
            output2qty[output.product.id] += Uom.compute_qty(
                output.uom, output.quantity * factor,
                output.product.default_uom,
                round=False)

        number = self.number
        state = self.state
        suffix = 2
        # The last "cut" is done after the loop
        remainder -= quantity
        if count:
            count -= 1
        productions = []
        while ((remainder - quantity) >= uom.rounding  # remainder > quantity
                and (count or count is None)):
            productions.append(self._split_production(
                    '%s-%02d' % (number, suffix), quantity, uom, input2qty,
                    output2qty))
            remainder -= quantity
            if count:
                count -= 1
            suffix += 1

        assert remainder > uom.rounding
        # The initial production contains the remaining quantity
        productions.append(self._split_production(
                '%s-%02d' % (number, suffix), quantity, uom, input2qty,
                output2qty))
        self.write([self], {
                'number': '%s-%02d' % (number, 1),
                'quantity': remainder,
                'uom': uom.id,
                'state': state,
                })
        self.write(productions, {'state': state})
        productions.append(self)
        return productions

    def _split_production(self, number, quantity, uom, input2qty, output2qty):
        production, = self.copy([self], {
                'number': number,
                'quantity': quantity,
                'uom': uom.id,
                'inputs': None,
                'outputs': None,
                })
        self._split_moves(self.inputs, production, input2qty,
            'production_input')
        self._split_moves(self.outputs, production, output2qty,
            'production_output')
        return production

    def _split_moves(self, current_moves, new_production, product2qty,
            relation_field):
        """
        Split <current_moves> getting the quantity per product specified in
        <product2qty> and "moving" it to <new_productoin> and leaving in
        current production <self> the remaining quantities.
        """
        pool = Pool()
        Move = pool.get('stock.move')
        Uom = pool.get('product.uom')

        product2pending_qty = product2qty.copy()
        to_draft, to_write, reset_state, new_moves = [], [], [], []
        for move in current_moves:
            pending_qty = Uom.compute_qty(
                move.product.default_uom, product2pending_qty[move.product.id],
                move.uom,
                round=False)
            if pending_qty < move.uom.rounding:
                # Leave this input to current production
                continue

            if (move.quantity - pending_qty) < move.uom.rounding:
                # move.quantity <= pending_qty
                # Move this input to new production
                product2pending_qty[move.product.id] -= Uom.compute_qty(
                    move.uom, move.quantity, move.product.default_uom,
                    round=False)
                to_write.extend(
                    ([move], {relation_field: new_production.id}))
                new_moves.append(move)
                continue

            # split move moving pending_qty to new production and leaving
            # remaining to current one
            product2pending_qty[move.product.id] = 0
            new_move_qty = move.uom.round(pending_qty)
            new_move, = Move.copy([move], {
                    relation_field: new_production.id,
                    'quantity': new_move_qty,
                    'state': 'draft',
                    })
            new_moves.append(new_move)
            to_write.extend(([move], {
                        'quantity': move.quantity - new_move_qty,
                        }))
            if move.state != 'draft':
                to_draft.append(move)
                reset_state.extend(
                    ([move, new_move], {'state': move.state}))

        # Reset to draft before the changes to avoid control over don't modify
        # non-draft moves
        if to_draft:
            Move.write(to_draft, {'state': 'draft'})
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

    def default_start(self, fields):
        pool = Pool()
        Production = pool.get('production')
        default = {}
        production = Production(Transaction().context['active_id'])
        if not production.product or not production.quantity:
            raise UserError(gettext('production_split.no_product_nor_quantity',
                production=production.rec_name))
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
