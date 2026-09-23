from ygc.extractors.serial import select_serial,extract_serial_candidates
def test_serial_number_label():
    c=select_serial('Vintage Fender. Serial number N056062. Excellent condition.'); assert c and c.value=='N056062' and c.confidence>=0.9
def test_s_n_label():
    c=select_serial('Fender Telecaster S/N: 729321, original finish.'); assert c and c.value=='729321'
def test_serial_and_fon_do_not_confuse():
    c=select_serial('Gibson Nick Lucas. Serial #83509; FON #9009.'); assert c and c.value=='83509'
def test_pot_code_not_selected_without_serial_label(): assert select_serial('Pot code 1377612, neck date 3 MAY 76.') is None
def test_year_alone_not_serial(): assert select_serial('Serial: 1976') is None
def test_multiple_candidates(): assert len(extract_serial_candidates('S/N: 123456. Serial number ABC999.'))>=2
