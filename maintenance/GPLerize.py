#!/usr/bin/env python3
import os
import sys
import shutil
import re
import datetime

def gplerize(source_dir):
    """
    Adds GPL notice to each source file in the specified directory.
    Ported from GPLerize.pl.
    """
    if not os.path.isdir(source_dir):
        print(f"Error: {source_dir} is not a directory.")
        sys.exit(1)

    # Generate copyright years dynamically (max 10 years per line)
    current_year = datetime.datetime.now().year
    years = [str(y) for y in range(2009, current_year + 1)]
    year_chunks = [years[i:i + 10] for i in range(0, len(years), 10)]
    copyright_lines = []
    for i, chunk in enumerate(year_chunks):
        year_str = ", ".join(chunk)
        suffix = "," if i < len(year_chunks) - 1 else ""
        if i == 0:
            copyright_lines.append(f" Copyright {year_str}{suffix}\n")
        else:
            copyright_lines.append(f"           {year_str}{suffix}\n")

    # Scan directory for source files
    try:
        files = os.listdir(source_dir)
    except OSError as e:
        print(f"Can't open the source directory: {e}")
        sys.exit(1)

    for file_name in files:
        name_lc = file_name.lower()
        
        # Ignore hidden/backup files starting with .#
        if name_lc.startswith('.#'):
            continue

        # Identify file types
        is_fortran_base = re.search(r'\.f(90)?$', name_lc)
        is_fortran = is_fortran_base or name_lc.endswith('.inc')
        is_c_style = name_lc.endswith(('.c', '.cpp', '.h'))

        if is_fortran or is_c_style:
            comment = "//" if is_c_style else "!!"
            file_path = os.path.join(source_dir, file_name)
            backup_path = file_path + "~"

            # Backup original file
            shutil.move(file_path, backup_path)

            try:
                with open(backup_path, 'r') as f_in, open(file_path, 'w') as f_out:
                    # Output GPL notice
                    for line in copyright_lines:
                        f_out.write(f"{comment}{line}")
                    f_out.write(f"{comment}    Andrew Benson <abenson@carnegiescience.edu>\n")
                    f_out.write(f"{comment}\n")
                    f_out.write(f"{comment} This file is part of Galacticus.\n")
                    f_out.write(f"{comment}\n")
                    f_out.write(f"{comment}    Galacticus is free software: you can redistribute it and/or modify\n")
                    f_out.write(f"{comment}    it under the terms of the GNU General Public License as published by\n")
                    f_out.write(f"{comment}    the Free Software Foundation, either version 3 of the License, or\n")
                    f_out.write(f"{comment}    (at your option) any later version.\n")
                    f_out.write(f"{comment}\n")
                    f_out.write(f"{comment}    Galacticus is distributed in the hope that it will be useful,\n")
                    f_out.write(f"{comment}    but WITHOUT ANY WARRANTY; without even the implied warranty of\n")
                    f_out.write(f"{comment}    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the\n")
                    f_out.write(f"{comment}    GNU General Public License for more details.\n")
                    f_out.write(f"{comment}\n")
                    f_out.write(f"{comment}    You should have received a copy of the GNU General Public License\n")
                    f_out.write(f"{comment}    along with Galacticus.  If not, see <http://www.gnu.org/licenses/>.\n\n")

                    # Strip old header and output remainder of code
                    # We detect the start of code by looking for lines that aren't empty 
                    # and don't start with the current comment style.
                    found_start = False
                    header_pattern = re.compile(rf"^\s*{re.escape(comment)}\s")
                    
                    for line in f_in:
                        if not found_start:
                            if not header_pattern.match(line) and line.strip() != "":
                                found_start = True
                        
                        if found_start:
                            f_out.write(line)
            except Exception as e:
                print(f"Error processing {file_name}: {e}")
                # Restore from backup if something went wrong
                shutil.move(backup_path, file_path)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: GPLerize.py <sourceDir>")
        sys.exit(1)
    gplerize(sys.argv[1])
