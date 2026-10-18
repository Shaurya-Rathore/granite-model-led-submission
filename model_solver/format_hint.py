"""Summarize a named row schema without repeating its branches or domains."""
import json


def named_format_hint(response_format):
    container=response_format['json_schema']['schema']['properties']['lines']
    if container.get('type')!='array':
        raise ValueError('Short named format requires a lines array')
    row=container['items'];variants=row.get('anyOf',[row]);fields={};ids=[];signatures=[]
    for variant in variants:
        for name,spec in variant['properties'].items():
            field=fields.setdefault(name,{'type':spec['type']})
            if name=='line':
                ids+=spec.get('enum',[])
            elif 'enum' in spec:
                field.setdefault('values',[]).extend(spec['enum'])
            if name=='facts':
                for fact in spec['items']['anyOf']:
                    op=fact['properties']['op']['enum'][0]
                    signatures.append(op+'('+','.join(k for k in fact['properties'] if k!='op')+')')
    for spec in fields.values():
        if 'values' in spec:spec['values']=list(dict.fromkeys(spec['values']))
    ids=list(dict.fromkeys(ids));signatures=list(dict.fromkeys(signatures))
    return ('\nJSON OUTPUT GUIDE: Return only an object with a lines array. Each row has exactly these fields: '+
        json.dumps(fields,separators=(',',':'))+'. Return exactly one row for every supplied source ID: '+
        json.dumps(ids,separators=(',',':'))+'. No duplicate rows or other IDs. '+
        'Each fact is a JSON object with op and the named fields in its signature: '+', '.join(signatures)+
        '. negated is a JSON Boolean. Use exact header labels and the task rules for empty/nonempty facts. '+
        'Do not output this guide or schema definitions; output the source interpretations.')
