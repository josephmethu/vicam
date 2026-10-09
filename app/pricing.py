"""Integer money, decimal quantities and explicit document-wide discount/VAT."""
import json
from decimal import Decimal, ROUND_HALF_UP
from pydantic import BaseModel, ConfigDict, Field, field_validator

class LineItem(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    description:str=Field(min_length=1,max_length=200)
    quantity:Decimal=Field(gt=0,le=1000000,max_digits=10,decimal_places=4)
    unit_amount_minor:int=Field(strict=True,ge=0,le=999999999999)

    @field_validator('quantity',mode='before')
    @classmethod
    def quantity_type(cls,value):
        if isinstance(value,bool):raise ValueError('Quantity must be a number')
        return value

def rounded(value):return int(value.quantize(Decimal('1'),rounding=ROUND_HALF_UP))

def calculate(items,discount_percent,vat_percent):
    lines=[]
    for item in items:
        data=item.model_dump(mode='json') if isinstance(item,LineItem) else dict(item)
        data['line_total_minor']=rounded(Decimal(str(data['quantity']))*data['unit_amount_minor'])
        lines.append(data)
    subtotal=sum(x['line_total_minor'] for x in lines)
    discount=rounded(Decimal(subtotal)*Decimal(str(discount_percent))/100)
    net=subtotal-discount;vat=rounded(Decimal(net)*Decimal(str(vat_percent))/100)
    total=net+vat
    if total<1 or total>999999999999:raise ValueError('Calculated total must be positive and within the supported amount range')
    return {'line_items':lines,'discount_percent':str(discount_percent),'vat_percent':str(vat_percent),
            'subtotal_minor':subtotal,'discount_minor':discount,'net_minor':net,'vat_minor':vat,'total_minor':total,
            'rounding':'Each line, then discount, then VAT rounded half up to the nearest minor unit; VAT applies after discount'}

def terms(snapshot):
    # Operational status and payments never revise the commercial terms of a copy.
    return {k:v for k,v in snapshot.items() if k not in {'paid_minor','balance_minor','status'}}
