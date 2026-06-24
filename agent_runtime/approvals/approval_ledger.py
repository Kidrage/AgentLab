class ApprovalLedger:
    def __init__(self):
        self.cards = {}
        
    def add_card(self, card):
        self.cards[card.id] = card
        
    def approve(self, id):
        if id in self.cards:
            self.cards[id].status = "approved"
            
    def reject(self, id):
        if id in self.cards:
            self.cards[id].status = "rejected"
