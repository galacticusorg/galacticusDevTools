#!/usr/bin/env python3

import sys
import os
import re
import shutil

def main():
    # Get source directory
    if len(sys.argv) != 2:
        print("Usage: GPLerize.py <sourceDir>")
        sys.exit(1)

    source_dir = sys.argv[1]

    # Check if the provided directory exists
    if not os.path.isdir(source_dir):
        print(f"Can't open the source directory: {source_dir}")
        sys.exit(1)

    # Base Output GPL Header (Fortran format)
    gpl_header_fortran = (
        "!! Copyright 2009, 2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018,\n"
        "!!           2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026\n"
        "!!    Andrew Benson <abenson@carnegiescience.edu>\n"
        "!!\n"
        "!! This file is part of Galacticus.\n"
        "!!\n"
        "!!    Galacticus is free software: you can redistribute it and/or modify\n"
        "!!    it under the terms of the GNU General Public License as published by\n"
        "!!    the Free Software Foundation, either version 3 of the License, or\n"
        "!!    (at your option) any later version.\n"
        "!!\n"
        "!!    Galacticus is distributed in the hope that it will be useful,\n"
        "!!    but WITHOUT ANY WARRANTY; without even the implied warranty of\n"
        "!!    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the\n"
        "!!    GNU General Public License for more details.\n"
        "!!\n"
        "!!    You should have received a copy of the GNU General Public License\n"
        "!!    along with Galacticus.  If not, see <http://www.gnu.org/licenses/>.\n\n"
    )

    # Automatically generate the C/C++ format by replacing Fortran comment markers
    gpl_header_c = gpl_header_fortran.replace("!!", "//")

    # Regular expression for matching blank lines
    regex_blank = re.compile(r'^\s*$')

    # Scan directory for source code
    for file_name in os.listdir(source_dir):
        file_name_lc = file_name.lower()
        file_path = os.path.join(source_dir, file_name)
        backup_path = file_path + "~"
        
        # Check matching file conditions
        is_fortran = file_name_lc.endswith(('.f', '.f90', '.inc'))
        is_c = file_name_lc.endswith(('.c', '.cpp', '.h'))
        is_not_lock_file = not file_name_lc.startswith('.#')

        if (is_fortran or is_c) and is_not_lock_file:
            # Determine correct header and comment regex based on file type
            if is_fortran:
                current_header = gpl_header_fortran
                # Match line starting with !!
                regex_comment = re.compile(r'^\s*!!\s')
            else:
                current_header = gpl_header_c
                # Match line starting with //
                regex_comment = re.compile(r'^\s*//\s')
            
            # Backup the file
            shutil.move(file_path, backup_path)
            
            with open(backup_path, 'r', encoding='utf-8', errors='replace') as in_hndl, \
                 open(file_path, 'w', encoding='utf-8') as out_hndl:
                
                # Output new GPL
                out_hndl.write(current_header)
                
                # Output remainder of code with previous GPL removed
                found_start = False
                for line in in_hndl:
                    if not found_start:
                        # Skip old header comments and blank lines at the top
                        if not regex_comment.match(line) and not regex_blank.match(line):
                            found_start = True
                    
                    if found_start:
                        out_hndl.write(line)

if __name__ == "__main__":
    main()
