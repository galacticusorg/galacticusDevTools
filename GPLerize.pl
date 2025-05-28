#!/usr/bin/env perl

# Adds a GPL notice to each source file. Often used to update the copyright years in all source files.
# Andrew Benson (28-Nov-2009)

# Get source directory.
if ( $#ARGV != 0) {die "Usage: GPLerize.pl <sourceDir>"};
my $sourceDir = $ARGV[0];

# Scan directory for Fotran source code.
opendir(indir,$sourceDir) or die "Can't open the source directory: #!";
while (my $fileName = readdir indir) {
    if (
	(
	 (	  
		  lc($fileName) =~ m/\.f(90)??$/  
		  && 
		  ! -e $srcdir."/".$fileName."t"
	 )
	 ||
	 lc($fileName) =~ m/\.f90t$/
	 ||
	 lc($fileName) =~ m/\.inc$/
	) 
	&&
	lc($fileName) !~ m/^\.\#/
	) {	    
	system("mv -f $sourceDir/$fileName $sourceDir/$fileName~");
	open(outHndl,">".$sourceDir."/".$fileName);
	open(inHndl,$sourceDir."/".$fileName."~");

        # Output GPL.
	print outHndl "!! Copyright 2009, 2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018,\n";
	print outHndl "!!           2019, 2020, 2021, 2022, 2023, 2024, 2025\n";
	print outHndl "!!    Andrew Benson <abenson\@carnegiescience.edu>\n";
	print outHndl "!!\n";
	print outHndl "!! This file is part of Galacticus.\n";
	print outHndl "!!\n";
	print outHndl "!!    Galacticus is free software: you can redistribute it and/or modify\n";
	print outHndl "!!    it under the terms of the GNU General Public License as published by\n";
	print outHndl "!!    the Free Software Foundation, either version 3 of the License, or\n";
	print outHndl "!!    (at your option) any later version.\n";
	print outHndl "!!\n";
	print outHndl "!!    Galacticus is distributed in the hope that it will be useful,\n";
	print outHndl "!!    but WITHOUT ANY WARRANTY; without even the implied warranty of\n";
	print outHndl "!!    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the\n";
	print outHndl "!!    GNU General Public License for more details.\n";
	print outHndl "!!\n";
	print outHndl "!!    You should have received a copy of the GNU General Public License\n";
	print outHndl "!!    along with Galacticus.  If not, see <http://www.gnu.org/licenses/>.\n\n";

        # Output remainder of code with previous GPL removed.
	$foundStart = 0;
	while ( $line = <inHndl> ) {
	    if ( $foundStart == 0 && $line !~ m/^\s*!!\s/ && $line !~ m/^\s*$/ ) {$foundStart = 1};
	    print outHndl $line unless ( $foundStart == 0 );
	}
	close(inHndl);
	close(outHndl);

    }
}
closedir(indir);

exit;
