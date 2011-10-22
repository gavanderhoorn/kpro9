#! /usr/bin/env python3
"""
A module for creating Wireshark dissectors from C structs.

Usage:
---------
usage: csjark.py [-h] [-v] [-d] [-n] [-i [header [header ...]]]
                 [-c [config [config ...]]] [-o [output]]
                 [header] [config]

Generate Wireshark dissectors from C structs.

positional arguments:
  header                C file to parse
  config                config file to parse

optional arguments:
  -h, --help            show this help message and exit
  -v, --verbose         print detailed information
  -d, --debug           print debugging information
  -n, --nocpp           disable C preprocessor
  -i [header [header ...]], --input [header [header ...]]
                        C file(s) to parse
  -c [config [config ...]], --config [config [config ...]]
                        configuration file(s) to parse
  -o [output], --output [output]
                        write output to directory/file

Example:
"python csjark.py -v -nocpp headerfile.h configfile.yml"
"""
import sys
import os
import argparse

import cparser
import config
import dissector


class Cli:
    """A class for handling command line interface parsing."""
    # TODO: update tests so we can move these to config.Options
    verbose = False
    debug = False
    strict = True # Quit if an unexpected exception is raised
    use_cpp = True
    output_dir = None # Store all output in a directory
    output_file = None # Store output in a single file

    @classmethod
    def parse_args(cls, args=None):
        """Parse arguments given in sys.argv.

        'args' is a list of strings to parse instead of sys.argv.
        """
        parser = argparse.ArgumentParser(
                description='Generate Wireshark dissectors from C structs.')

        # A single C header file
        parser.add_argument('header', nargs='?', help='C file to parse')

        # A single config file
        parser.add_argument('config', nargs='?', help='config file to parse')

        # Verbose flag
        parser.add_argument('-v', '--verbose', action='store_true',
                default=cls.verbose, help='print detailed information')

        # Debug flag
        parser.add_argument('-d', '--debug', action='store_true',
                default=cls.debug, help='print debugging information')

        # No CPP flag
        parser.add_argument('-n', '--nocpp', action='store_false', dest='nocpp',
                default=cls.use_cpp, help='disable C preprocessor')

        # A list of C header files
        parser.add_argument('-i', '--input', metavar='header',
                default=[], nargs='*', help='C file(s) to parse')

        # Configuration file
        parser.add_argument('-c', '--config', metavar='config', dest='configs',
                 default=[], nargs='*', help='configuration file(s) to parse')

        # Write output to destination file
        parser.add_argument('-o', '--output', metavar='output',
                nargs='?', help='write output to directory/file')

        # Parse arguments
        if args is None:
            namespace = parser.parse_args()
        else:
            namespace = parser.parse_args(args)

        cls.verbose = namespace.verbose
        cls.debug = namespace.debug
        cls.use_cpp = namespace.nocpp

        headers = namespace.input
        if namespace.header:
            headers.append(namespace.header)

        configs = namespace.configs
        if namespace.config:
            configs.append(namespace.config)

        # If only a .yml file is given, move it to configs
        if len(headers) == 1 and not configs and headers[0][-4:] == '.yml':
            configs.append(headers.pop())

        # Find out where to store output from the generator
        if namespace.output:
            path = os.path.join(os.path.dirname(sys.argv[0]), namespace.output)
            if os.path.isdir(path):
                cls.output_dir = path
            else:
                cls.output_file = path

        # Need to provide either a header file or a config file
        if not headers and not configs:
            parser.print_help()
            sys.exit(2)

        # Make sure the files provided actually exists
        missing = [i for i in headers + configs if not os.path.exists(i)]
        if missing:
            print('Unknown file(s): %s' % ', '.join(missing))
            sys.exit(2)

        # Add files if headers or configs contain folders
        def files_in_folder(var, file_extensions):
            i = 0
            while i < len(var):
                if os.path.isdir(var[i]):
                    Cli.strict = False # Batch processing
                    folder = var.pop(i)
                    var.extend(os.path.join(folder, path) for path in
                            os.listdir(folder) if os.path.isdir(path)
                            or os.path.splitext(path)[1] in file_extensions)
                else:
                    i += 1

        files_in_folder(headers, ('.h', '.c'))
        files_in_folder(configs, ('.yml', ))

        # Update Options
        config.Options.verbose = Cli.verbose
        config.Options.debug = Cli.debug
        config.Options.strict = Cli.strict
        config.Options.use_cpp = Cli.use_cpp

        return headers, configs


def create_dissector(filename, options):
    """Create a Wireshark dissector from 'filename'."""

    # Handle different platforms
    protocols = {}
    for platform in options.platforms:

        # Parse the filename and find all struct definitions
        try:
            # TODO: create platform specfic macro header file
            ast = cparser.parse_file(filename, use_cpp=options.use_cpp)
            protocols[platform.name] = cparser.find_structs(ast, platform)

        # Silence errors if not in strict mode
        except Exception as err:
            if options.strict:
                raise
            else:
                print('Skipped "%s":%s as it raised %s' % (
                        filename, platform.name, repr(err)))
                if options.debug:
                    sys.excepthook(*sys.exc_info())
                    print()
                continue

    if options.debug:
        ast.show()

    # Delete output_file if it already exists
    if Cli.output_file and os.path.isfile(Cli.output_file):
        os.remove(Cli.output_file)

    # Generate and write lua dissectors
    protocols_count = 0
    for platform_name, protos in protocols.items():
        for proto in protos:
            protocols_count += 1
            code = proto.create()

            path = '%s.%s.lua' % (proto.name, platform_name)
            flag = 'w'
            if Cli.output_dir:
                path = '%s/%s' % (Cli.output_dir, path)
            elif Cli.output_file:
                path = Cli.output_file
                flag = 'a'

            with open(path, flag) as f:
                f.write(code)

    return protocols_count


def main():
    """Run the CSjark program."""
    headers, configs = Cli.parse_args()

    # Parse config files
    options = config.Options
    for filename in configs:
        config.parse_file(filename)

        if options.verbose:
            print("Parsed config file '%s' successfully." % filename)


    # Add current platform to list of platforms if its empty
    options.create_default_platform()

    # Create a delegator for delegating messages to the right dissector
    options.delegator = dissector.Delegator(options.platforms)

    # Create dissectors
    dissector_count = 0
    for filename in headers:
        dissector_count += create_dissector(filename, options)

        if options.verbose:
            print("Parsed header file '%s' successfully." % filename)

    print("Successfully parsed %i file(s), created %i dissector(s)." % (
            len(headers), dissector_count))

    # Write the delegator to file
    with open('luastructs.lua', 'w') as f:
        f.write(options.delegator.create())


if __name__ == "__main__":
    main()

