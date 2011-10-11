"""
A module for Wireshark specific data structures and functions.
"""
from config import Range, Enum, Bitstring, Dissector
from dissector import (Field, EnumField, RangeField,
                        ArrayField, BitField, DissectorField, SubDissectorField)


# Mapping of c type and their wireshark field type.
DEFAULT_C_TYPE_MAP = {
        'bool': 'bool',
        'char': 'string',
        'signed char': 'string',
        'unsigned char': 'string',
        'short': "int16",
        'signed short': "int16",
        'unsigned short': "uint16",
        'short int': "int16",
        'signed short int': "int16",
        'unsigned short int': "uint16",
        "int": "int32",
        'signed int': "int32",
        'unsigned int': "uint32",
        'long': "int64",
        'signed long': "int64",
        'unsigned long': "uint64",
        'long int': "int64",
        'signed long int': "int64",
        'unsigned long int': "uint64",
        'long long': "int64",
        'signed long long': "int64",
        'unsigned long long': "uint64",
        'long long int': "int64",
        'signed long long int': "int64",
        'unsigned long long int': "uint64",
        'float': 'float',
        'double': 'double',
        'long double': 'todo',
        'pointer': 'int32',
        'enum': 'uint32',
}


# Mapping of c type and their default size in bytes.
DEFAULT_C_SIZE_MAP = {
        'bool': 1,
        'char': 1,
        'signed char': 1,
        'unsigned char': 1,
        'short': 2,
        'signed short': 2,
        'unsigned short': 2,
        'short int': 2,
        'signed short int': 2,
        'unsigned short int': 2,
        'int': 4,
        'signed int': 4,
        'unsigned int': 4,
        'long': 8,
        'signed long': 8,
        'unsigned long': 8,
        'long int': 8,
        'signed long int': 8,
        'unsigned long int': 8,
        'long long': 8,
        'signed long long': 8,
        'unsigned long long': 8,
        'long long int': 8,
        'signed long long int': 8,
        'unsigned long long int': 8,
        'float': 4,
        'double': 8,
        'long double': 16,
        'pointer': 4,
        'enum': 4,
}


def map_type(ctype):
    """Find the wireshark type for a ctype."""
    return DEFAULT_C_TYPE_MAP.get(ctype, ctype)


def size_of(ctype):
    """Find the size of a c type in bytes."""
    if ctype in DEFAULT_C_SIZE_MAP.keys():
        return DEFAULT_C_SIZE_MAP[ctype]
    else:
        return 1


def create_enum(proto, name, values):
    """Create a dissector field representing an enum."""
    type, size = map_type('enum'), size_of('enum')
    proto.add_field(EnumField(name, type, size, values))


def create_array(proto, name, ctype, size, depth):
    """Create a dissector field representing an array."""
    proto.add_field(ArrayField(name, map_type(ctype), size, depth))

def create_struct(proto, type_name, name, structs):
    struct = structs[type_name]
    size = struct.get_size()
    id = struct.id
    proto.add_field(SubDissectorField(name, id, size, 'struct'))



def create_field(proto, name, ctype, size=None):
    """Create a dissector field representing the struct member."""
    field = None

    type_ = map_type(ctype)
    if size is None:
        size = size_of(ctype)

    # Find all rules relevant for this field
    # Todo: what if several rules cover one member?
    #       now we simply discard all but one rule, try to merge them?
    if proto.conf is not None:
        rules = proto.conf.get_rules(name, ctype)

        # Dissector rules
        diss = [i for i in rules if isinstance(i, Dissector)]
        if diss and field is None:
            field = DissectorField(diss[0].name, diss[0].size)

        # Bit string rules
        bits = [i for i in rules if isinstance(i, Bitstring)]
        if bits and field is None:
            field = BitField(name, type_, size, bits[0].bits)

        # Enum rules
        enums = [i for i in rules if isinstance(i, Enum)]
        if enums and field is None:
            rule = enums[0]
            field = EnumField(name, type_, size, rule.values, rule.strict)

        # Range rules
        ranges = [i for i in rules if isinstance(i, Range)]
        if ranges and field is None:
            rule = ranges[0]
            field = RangeField(name, type_, size, rule.min, rule.max)

    if field is None:
        field = Field(name, type_, size)

    proto.add_field(field)


