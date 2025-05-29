from odoo import models, fields, api, _
from odoo.exceptions import UserError


class AccountBankStatementFaildImport(models.TransientModel):
    _name = "account.bank.statement.faild.import"
    _description = "Account Bank Failed Statement Import Lines"

    line_ids = fields.One2many(
        'account.bank.statement.faild.import.lines',
        'statement_faild_id',
        string=_('Lines'),
    )

    journal_id = fields.Many2one(
        'account.journal',
        string=_('Journal'),
        required=True,
    )

    def action_open_faild_statements_wizard(self, id):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Failed Statements'),
            'view_mode': 'form',
            'res_model': 'account.bank.statement.faild.import',
            'res_id': id,
            'target': 'new',
            'nodestroy': True,
            'context': self.env.context,
        }
    
    def _refreshes_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'account.bank.statement.faild.import',
            'res_id': self.id,
            'target': 'new',
        }
    
    def mark_all_line_to_import(self):
        for line in self.line_ids:
            line.import_faild_statement = True
        return self._refreshes_wizard()
    
    def mark_all_like_debit(self):
        for line in self.line_ids:
            line.type_transaction = 'debit'
        return self._refreshes_wizard()

    def mark_all_like_credit(self):
        for line in self.line_ids:
            line.type_transaction = 'credit'
        return self._refreshes_wizard()
    
    def import_bank_statement(self):
        lines = self.line_ids.filtered(lambda l: l.import_faild_statement)

        if len(lines) <= 0:
            raise UserError(_('You must select at least one statement to import'))
        
        AccountBanckStatementLine = self.env['account.bank.statement.line']
        lines_imported = []
        for line in lines:
            if line.type_transaction == 'none':
                raise UserError(_('You must select a type of transaction to import'))
            
            if not line.date:
                raise UserError(_('You must select a date to import'))
            
            if not line.amount or line.amount == 0:
                raise UserError(_('You must select an amount to import'))
            
            amount = 0
            if line.type_transaction == 'debit':
                amount = line.amount if line.is_for_credit_card else -line.amount
            elif line.type_transaction == 'credit':
                amount = -line.amount if line.is_for_credit_card else line.amount

            unique_import_id = '%s-%s-%s-%s-%s-%s' % (
                line.journal_id.l10n_do_bank,
                line.date, 
                line.payment_ref, 
                line.amount, 
                line.type_transaction, 
                line.journal_id.id
            )

            statement_line = AccountBanckStatementLine.sudo().create({
                'date': line.date,
                'payment_ref': line.payment_ref,
                'amount': amount,
                'statement_id': line.statement_id.id,
                'unique_import_id': unique_import_id
            })    
            line.statement_id.line_ids = [(4, statement_line.id)]
            lines_imported.append(line.id)
        self.line_ids = [(3, line) for line in lines_imported]
        if len(self.line_ids) == 0:
            return
        return self._refreshes_wizard()

    def drop_bank_statement(self):
        self.line_ids = [(3, line.id) for line in self.line_ids]
        return

    
class AccountBankStatementFaildImportLines(models.TransientModel):
    _name = "account.bank.statement.faild.import.lines"
    _description = "Account Bank Failed Statement Import Lines"

    import_faild_statement = fields.Boolean(
        string=_('Import Statement'),
        default=False,
    )

    statement_import_id = fields.Many2one(
        'account.bank.statement.import',
        string=_('Statement'),
        required=True,
    )

    statement_faild_id = fields.Many2one(
        'account.bank.statement.faild.import',
        string=_('Statement'),
    )

    journal_id = fields.Many2one(
        'account.journal',
        string=_('Journal'),
        required=True,
    )

    statement_id = fields.Many2one(
        'account.bank.statement',
        string=_('Statement'),
        required=True,
    )

    date = fields.Date(
        string=_('Date'),
    )

    payment_ref = fields.Char(
        string=_('Description'),
        required=True,
    )

    amount = fields.Float(
        string=_('Amount'),
    )

    type_transaction = fields.Selection(
        selection=[('none', _('None')), ('debit', _('Debit')), ('credit', _('Credit'))],
        string=_('Type Transaction'),
        required=True,
    )

    unique_import_id = fields.Char(
        string=_('Unique ID'),
    )

    is_for_credit_card = fields.Boolean(
        string=_('Is a credit card?'),
        default=False,
        help=_('Mark if this journaal is for a credit card, this option will invert the ammounts the credit passed to the debit and vice versa'),
    )