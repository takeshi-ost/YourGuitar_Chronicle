from ygc.extractors.normalization import normalize_manufacturer,normalize_model,normalize_serial
def match_or_create(repo,manufacturer,model,serial_number):
    nm=normalize_manufacturer(manufacturer); nmo=normalize_model(model); ns=normalize_serial(serial_number)
    if not nm or not ns: raise ValueError('manufacturer and serial_number are required')
    e=repo.find_individual(nm,nmo,ns)
    if e: return int(e['id'])
    return repo.create_individual(manufacturer,model,serial_number,nm,nmo,ns)
