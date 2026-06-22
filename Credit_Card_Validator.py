# luhn algorithm


class CreditCard:
    def __init__(self, card_no):
        # Strip spaces, dashes, and other non-digit characters
        self.card_no = ''.join(c for c in card_no if c.isdigit())

    @property
    def company(self):
        comp = None
        if self.card_no.startswith('4'):
            comp = 'Visa Card'
        elif self.card_no.startswith(('5018', '5020', '5038', '5893', '6304', '6759', '6761', '6762', '6763', '50', '67', '58', '63')):
            comp = 'Maestro Card'
        elif self.card_no.startswith(('51', '52', '53', '54', '55')) or (len(self.card_no) >= 4 and 2221 <= int(self.card_no[:4]) <= 2720):
            comp = 'Master Card'
        elif self.card_no.startswith(('34', '37')):
            comp = 'American Express Card'
        elif self.card_no.startswith('62'):
            comp = 'Unionpay Card'
        elif self.card_no.startswith(('6011', '644', '645', '646', '647', '648', '649', '65', '6')):
            comp = 'Discover Card'
        elif len(self.card_no) >= 4 and 3528 <= int(self.card_no[:4]) <= 3589:
            comp = 'JCB Card'
        elif self.card_no.startswith('7'):
            comp = 'Gasoline Card'

        if comp is None:
            return 'Company : Unknown'
        return 'Company : ' + comp

    def first_check(self):
        if 13 <= len(self.card_no) <= 19:
            message = "First check : Valid in terms of length."
        else:
            message = "First check : Check Card number once again it must be of 13 to 19 digits long."
        return message

    def validate(self):
        if not self.card_no:
            return 'Invalid Card'
        # double every second digit from right to left
        sum_ = 0
        crd_no = self.card_no[::-1]
        for i in range(len(crd_no)):
            if i % 2 == 1:
                double_it = int(crd_no[i]) * 2
                if double_it > 9:
                    sum_ += (double_it // 10) + (double_it % 10)
                else:
                    sum_ += double_it
            else:
                sum_ += int(crd_no[i])

        if sum_ % 10 == 0:
            response = "Valid Card"
        else:
            response = 'Invalid Card'

        return response

    @property
    def checksum(self):
        if not self.card_no:
            return '#CHECKSUM# : None'
        return '#CHECKSUM# : ' + self.card_no[-1]

    @classmethod
    def set_card(cls, card_to_check):
        return cls(card_to_check)


if __name__ == "__main__":
    card_number = input("Enter card number: ")
    card = CreditCard.set_card(card_number)
    print(card.company)
    print('Card : ', card.card_no)
    print(card.first_check())
    print(card.checksum)
    print(card.validate())

# 79927398713
# 4388576018402626
# 379354508162306
