# -*- coding: utf-8 -*-
# Copyright (C) 2011 Even Wiik Thomassen, Erik Bergersen,
# Sondre Johan Mannsverk, Terje Snarby, Lars Solvoll Tønder,
# Sigurd Wien and Jaroslav Fibichr.
#
# This file is part of CSjark.
#
# CSjark is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# CSjark is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with CSjark.  If not, see <http://www.gnu.org/licenses/>.
"""
A module for generating Lua dissectors for Wireshark.

The Disssector class is a container of platform-specific Wirehsark
fields instances and subclasses. The Protocol class is a collection of
dissector-instances for each platform it should support. The Delegator
class is a subclass of both these classes, and generates 'luastructs.lua'
which decides which Wireshark dissector to call from each message id.
"""
from platform import Platform
from field import create_lua_var, create_lua_valuestring, BaseField, Field


class Dissector(BaseField):
    """A Dissector is a collection of fields and code.

    It's used to generate Wireshark dissectors written in Lua, for
    dissecting a packet into a set of fields with values.
    """

    def __init__(self, name, platform, conf=None):
        """Create a new dissector instance.

        'name' is the protocol name
        'platform' is the platform dissecting messages from
        'conf' is an optional config object
        """
        self.name = name
        self.platform = platform
        self.endian = platform.endian
        self.conf = conf

        self.field_var = 'f.'
        from config import Options
        if len(Options.platforms) > 1:
            self.field_var += create_lua_var(platform.name)

        self.children = [] # List of all child fields

        self._pushed = False
        self._increase_offset = True

    @property
    def alignment(self):
        """Find the alignment size of the fields in the protocol."""
        return max([0] + [f.alignment for f in self.children])

    @property
    def size(self):
        """Find the size of the fields in the protocol."""
        size = 0
        for field in self.children:
            if field.size:
                size = self.get_padding(field, size)
                size += field.size
        return self.get_padding(self, size)

    def add_field(self, field):
        """Add a field to the dissectors list of field."""
        self.children.append(field)
        return field

    def push_modifiers(self):
        """Push prefixes and postfixes down to child fields."""
        if self._pushed:
            return
        self._pushed = True
        for field in self.children:
            field.var_prefix.insert(0, self.field_var)
            field.abbr_prefix.insert(0, self.name)
            field.push_modifiers()

    def get_definition(self):
        """Get the ProtoField definition for this field."""
        data = []

        for field in self.children:
            code = field.get_definition()

            if self.conf and self.conf.cnf: # Conformance file code
                code = self.conf.cnf.match(field.name, code, definition=True)
            data.append(code)

        # Conformance file definition code extra
        if self.conf and self.conf.cnf:
            data.append(self.conf.cnf.match(None, None, definition=True))

        return '\n'.join(i for i in data if i is not None)

    def get_code(self, offset, store=None, tree='subtree'):
        """Get the code for dissecting this field."""
        self.offset = offset
        data = []

        for field in self.children:
            offset = self.get_padding(field, offset)
            code = field.get_code(offset, store=store, tree=tree)

            # Conformance file code
            if self.conf and self.conf.cnf:
                code = self.conf.cnf.match(field.name, code, False, field)
            data.append(code)

            if self._increase_offset:
                offset += field.size

        # Conformance file dissection function code extra
        if self.conf and self.conf.cnf:
            data.append(self.conf.cnf.match(None, None, definition=False))

        # Delegate rest of buffer to any trailing protocols
        if self.conf and self.conf.trailers:
            data.append(self._trailers(self.conf.trailers, offset))

        return '\n'.join(i for i in data if i is not None)

    def get_padding(self, field, offset):
        """Get padding for correct alignment."""
        alignment = field.alignment
        padding = 0
        if alignment:
            padding = (alignment - offset) % alignment
            if padding >= alignment:
                padding = 0
        return offset + padding

    def _trailers(self, rules, offset):
        """Add code for handling of trailers to the protocol."""
        data = ['\n\t-- Trailers handling for struct: %s' % self.name]

        # Offset variable and variable declaration
        off_var = 'trail_offset'
        t_offset = '\tlocal {var} = {offset}'
        data.append(t_offset.format(offset=offset, var=off_var))

        for i, rule in enumerate(rules):
            # Find the count
            if rule.member is not None:
                # Find offset, size and func_type
                fields = [i for i in self.children if i.name == rule.member]
                if not fields:
                    continue # rule.member don't exists in the struct
                func = fields[0].func_type

                count = 'trail_count'
                t = '\tlocal {var} = buffer({off}, {size}):{func}()'
                data.append(t.format(off=fields[0].offset,
                                 var=count, size=fields[0].size, func=func))
            else:
                count = rule.count

            size_str = ''
            if rule.size is not None:
                size_str = ', %i' % rule.size

            # Call trailers 'count' times
            tabs = '\t'
            if rule.member is not None or count > 1:
                data.append('\tfor i = 1, {count} do'.format(count=count))
                tabs += '\t'

            t1 = '{tabs}local trailer = Dissector.get("{name}")'
            t2 = '{tabs}trailer:call(buffer({off}{size}):tvb(), pinfo, tree)'
            t3 = '{tabs}{var} = {var} + {size}'
            data.append(t1.format(tabs=tabs, name=rule.name))
            data.append(t2.format(tabs=tabs, off=off_var, size=size_str))

            # Update offset after all but last trailer
            if i < len(rules)-1:
                data.append(t3.format(tabs=tabs,
                                           var=off_var, size=rule.size))

            if rule.member is not None or count > 1:
                data.append('\tend') # End for loop

        return '\n'.join(i for i in data if i is not None)


class UnionDissector(Dissector):
    """A Dissector where each field does not increase the offset."""

    def __init__(self, *args, **vargs):
        """Create a new UnionDissector instance."""
        super().__init__(*args, **vargs)
        self._increase_offset = False

    @property
    def size(self):
        """Find the size of the fields in the protocol."""
        return self.get_padding(self, max(
                [0] + [field.size for field in self.children]))


class Protocol:
    """A Protocol is a collection of platform specific dissectors.

    It's used to generate Wireshark dissectors written in Lua, for
    dissecting a packet into a set of fields with values.
    """

    REGISTER_FUNC = 'delegator_register_proto'

    protocols = {} # Map protocol name to instance

    def __init__(self, name, id=None, description=None):
        """Create a Protocol, for generating a dissector.

        'name' is the name of the Protocol to dissect
        'id' a list of message id's
        'description' the description of the protocol to dissect
        """
        if description is None:
            description = 'struct %s' % name
        self.name = name
        self.id = id
        self.description = description
        self.dissectors = {} # Map platform names to dissectors
        self.var = create_lua_var('proto_%s' % name)

    def get_dissector(self, platform):
        """Get a dissector for a given 'platform'."""
        return self.dissectors.get(platform.name, None)

    @classmethod
    def create_dissector(cls, name, platform=None, conf=None, union=False):
        """Create a new dissector and protocol if needed."""
        if platform is None:
            platform = Platform.mappings['default']

        # Create a new Protocol if one does not already exists
        try:
            proto = cls.protocols[name]
        except KeyError:
            vargs = {}
            if conf is not None:
                vargs['id'] = conf.id
                vargs['description'] = conf.description
            proto = Protocol(name, **vargs)
            cls.protocols[name] = proto

        # Create the actual dissector or union dissector
        if not union:
            dissector = Dissector(name, platform, conf)
        else:
            dissector = UnionDissector(name, platform, conf)
        proto.dissectors[platform.name] = dissector

        return proto, dissector

    def generate(self):
        """Returns all the code for dissecting this protocol."""
        for child in self.dissectors.values():
            child.push_modifiers()

        # Create dissector content
        data = []
        data.append(self._legal_header())
        data.append(self._header_defintion())
        data.append(self._fields_definition())
        data.append(self._dissector_func())
        data.append(self._register_dissector())
        return '\n'.join(i for i in data if i is not None)

    def _legal_header(self):
        """Add the legal header with license info."""
        pass

    def _header_defintion(self):
        """Add the code for the header of the protocol."""
        data = []
        comment = '-- Dissector for %s' % self.name
        if self.description:
            comment += ': %s' % self.description
        data.append(comment)

        proto = 'local {var} = Proto("{name}", "{description}")\n'
        data.append(proto.format(var=self.var, description=self.description,
                name=self.name.lower().replace(' ', '_')))
        return '\n'.join(data)

    def _fields_definition(self):
        """Add code for defining the ProtoField's in the protocol."""
        data = ['-- ProtoField defintions for: %s' % self.name]
        decl = 'local {field_var} = {var}.fields'
        data.append(decl.format(field_var='f', var=self.var))
        for child in self.dissectors.values():
            data.append(child.get_definition())
        data.append('')
        return '\n'.join(i for i in data if i is not None)

    def _dissector_func(self):
        """Add the code for the dissector function for the protocol."""
        data = ['-- Dissector function for: %s' % self.name]

        def retrieve_pinfo():
            data.append('\tif pinfo.private.field_name then')
            t = '\t\tsubtree:set_text(pinfo.private.field_name .. ": {name}")'
            data.append(t.format(name=child.name))
            data.append('\t\tpinfo.private.field_name = nil\n\telse')
            t = '\t\tpinfo.cols.info:append("({desc})")'
            data.append(t.format(desc=self.description))
            data.append('\tend')

        # Dissector function
        func_diss = 'function {var}.dissector(buffer, pinfo, tree)'
        data.append(func_diss.format(var=self.var))

        # Retrieve flag value from private info table
        flag_var = create_lua_var('flag')
        flag = '\tlocal {var} = tonumber(pinfo.private.platform_flag)'
        data.append(flag.format(var=flag_var))

        # If only 1 or less dissectors, insert dissector code directly
        if len(self.dissectors) < 2:
            if self.dissectors:
                child = list(self.dissectors.values())[0]
                sub_tree = '\tlocal subtree = tree:{add}({var}, buffer())'
                data.append(sub_tree.format(add=child.add_var, var=self.var))
                retrieve_pinfo()
                data.append(child.get_code(0))
            data.extend(['end', ''])
            return '\n'.join(i for i in data if i is not None)

        # Get flags and call the platform specific function
        table = {}
        for child in self.dissectors.values():
            child._func_name = create_lua_var(
                    '%s_%s' % (self.var, child.platform.name))
            table[child.platform.flag] = child._func_name
        table = create_lua_valuestring(table, wrap=False)
        data.append('\tlocal func_mapping = {table}'.format(table=table))
        data.append('\tif func_mapping[{var}] then'.format(var=flag_var))
        call = '\t\t func_mapping[{var}](buffer, pinfo, tree)'
        data.append(call.format(var=flag_var))
        data.extend(['\tend', 'end', ''])

        # Modify name if sub-dissector
        pinfo_func = create_lua_var('%s_pinfo_magic' % self.var)
        data.append('-- Function for retrieving parent dissector name')
        data.append('function {func}(pinfo, subtree)'.format(func=pinfo_func))
        retrieve_pinfo()
        data.extend(['end', ''])

        # Create dissector function for each dissector
        for child in self.dissectors.values():
            data.append('-- Dissector function for: %s (platform: %s)' % (
                    child.name, child.platform.name))
            func = 'function {name}(buffer, pinfo, tree)'
            data.append(func.format(name=child._func_name))

            # Add subtree
            sub_tree = '\tlocal subtree = tree:{add}({var}, buffer())'
            data.append(sub_tree.format(add=child.add_var, var=self.var))
            data.append('\t{func}(pinfo, subtree)'.format(func=pinfo_func))

            # Add the actual field code for each field
            data.append(child.get_code(0))
            data.extend(['end', ''])

        return '\n'.join(i for i in data if i is not None)

    def _register_dissector(self):
        """Add code for registering the dissector in the dissector table."""
        # Dissector message id, which maps to name
        if self.id is None:
            message_ids = ['nil']
        else:
            message_ids = self.id

        # Dissector Sizes and platforms
        sizes = {i.platform.flag: i.size for i in self.dissectors.values()}
        sizes = create_lua_valuestring(sizes, wrap=False)

        data = []
        for id in message_ids:
            data.append('{func}({var}, "{name}", {id}, {sizes})'.format(
                    func=self.REGISTER_FUNC, var=self.var,
                    name=self.name, id=id, sizes=sizes))
        data.extend(['', ''])
        return '\n'.join(i for i in data if i is not None)


class Delegator(Dissector, Protocol):
    """A class for delegating dissecting to protocols.

    Creates the top-level lua dissector which delegates the task
    of dissecting specific messages to dissectors generated by
    Protocol instances.

    This top-level dissector contains code for finding the platform
    the message originates from, and finds which specific dissector
    handles that platform and message.
    """

    def __init__(self, platforms):
        """Create a new delegator instance.

        'platforms' is a set of all platforms to support
        """
        super().__init__('luastructs', Platform.mappings['default'], None)
        self.platforms = platforms
        self.field_var = 'f.'
        self.description = 'Lua C Structs'
        self.dissectors = {self.platform.name: self}

        self.var = create_lua_var('delegator')
        self.table_var = create_lua_var('dissector_table')
        self.id_table = create_lua_var('message_ids')
        self.sizes_table = create_lua_var('dissector_sizes')
        self.msg_var = create_lua_var('msg_node')

        # Add fields, don't change sizes!
        endian = Platform.big
        self.add_field(Field('Version', 'uint8', 1, 0, endian))
        values = {p.flag: p.name for name, p in self.platforms.items()}
        field = Field('Flags', 'uint8', 1, 0, endian)
        field.set_list_validation(values)
        self.add_field(field)
        self.add_field(Field('Message', 'uint16', 2, 0, endian))
        self.add_field(Field('Message length', 'uint32', 4, 0, endian))

        self.version, self.flags, self.msg_id, self.length = self.children

    def generate(self):
        """Returns all the code for dissecting this protocol."""
        self.push_modifiers()

        data = []
        data.append(self._legal_header())
        data.append(self._header_defintion())
        data.append(self._fields_definition())
        data.append(self._register_function())
        data.append(self._dissector_func())
        return '\n'.join(i for i in data if i is not None)

    def _header_defintion(self):
        """Add the code for the header of the protocol."""
        data = ['-- Delegator for %s dissectors' % self.name]

        # Create the different dissector tables
        t = 'local {var} = DissectorTable.new("{name}", "Lua Structs", ftypes.STRING)'
        data.append(t.format(var=self.table_var, name=self.name))

        # Create the delegator dissector
        proto = 'local {var} = Proto("{name}", "{description}")'
        data.append(proto.format(var=self.var, name=self.name,
                                      description=self.description))

        # Add the message id and dissector sizes tables
        data.append('local {var} = {{}}'.format(var=self.id_table))
        data.append('local {var} = {{}}\n'.format(var=self.sizes_table))
        return '\n'.join(i for i in data if i is not None)

    def _register_function(self):
        """Add code for register protocol function."""
        return """\
-- Register struct dissectors
function {func}(proto, name, id, sizes)
    {table}:add(name, proto)
    if id ~= nil then {ids}[id] = name end
    if sizes ~= nil then
	for flag, size in pairs(sizes) do
	    if {sizes}[flag] == nil then
                {sizes}[flag] = {{}}
	    end
	    if {sizes}[flag][size] == nil then
		{sizes}[flag][size] = {{}}
	    end
	    table.insert({sizes}[flag][size], name)
	end
    end
end\n""".format(func=self.REGISTER_FUNC,
        table=self.table_var, ids=self.id_table, sizes=self.sizes_table)

    def _dissector_func(self):
        """Add the code for the dissector function for the protocol."""
        data = ['-- Delegator dissector function for %s' % self.name]

        # Add dissector function
        data.append('function delegator.dissector(buffer, pinfo, tree)')
        data.append('\tlocal subtree = tree:add(delegator, buffer())')
        data.append('\tpinfo.cols.protocol = delegator.name')
        data.append('\tpinfo.cols.info = delegator.description\n')

        # Fields code
        data.append(self.version.get_code(0))
        data.append(self.flags.get_code(1))
        t = '\tpinfo.private.platform_flag = {flag}'
        data.append(t.format(flag=self.flags._value_var))
        data.append(self.msg_id.get_code(2, store=self.msg_var))
        t = '\tsubtree:add(f.messagelength, buffer(4):len()):set_generated()'
        data.extend([t, ''])

        # Find message id and flag
        msg_var = create_lua_var('id_value')
        data.append(self.msg_id._store_value(msg_var))
        data.append(self.length._store_value('length_value', offset=4))
        data.append('')

        # Call the right dissector
        data.append('\t-- Call the correct dissector, or try and guess which')
        data.append('''\
    if {ids}[{msg}] then
        {node}:append_text(" (" .. {ids}[{msg}] ..")")
        {table}:try({ids}[{msg}], buffer(4):tvb(), pinfo, tree)
    else
        {node}:add_expert_info(PI_MALFORMED, PI_WARN, "Unknown message id")
        if {sizes}[{flag}] and {sizes}[{flag}][{length}] then
            for key, value in pairs({sizes}[{flag}][{length}]) do
                {table}:try(value, buffer(4):tvb(), pinfo, tree)
            end
        end
    end\nend\n\n'''.format(ids=self.id_table, msg=msg_var, node=self.msg_var,
                sizes=self.sizes_table, flag=self.flags._value_var,
                table=self.table_var, length=self.length._value_var))

        return '\n'.join(i for i in data if i is not None)

