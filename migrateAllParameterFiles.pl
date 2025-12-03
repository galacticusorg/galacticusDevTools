#!/usr/bin/env perl
use strict;
use warnings;
use File::Find;
use XML::LibXML qw(:libxml);
use DateTime;

# Script used to automate migration of all parameter files.
# Andrew Benson (23-May-2025).

# Simply run the script from a Galacticus directory.

# Get a timestamp for the update.
my $timeStamp = DateTime->now();

# Migrate all files.
my @parameterPaths = ( "parameters", "constraints", "testSuite" );
find(\&runMigrations,@parameterPaths);

# Reset an outdated revision is test suite parameter files that explicitly probe this issue.
foreach my $file ( "strictOutdated.xml", "unstrictOutdated.xml" ) {
    system("sed -r s/'lastModified\s+revision=\"[a-f0-9]+\"'/'lastModified\s+revision=\"262562000c251ee5b935019673f606a8a8c47c10\"'/ testSuite/parameters/".$file);
}

exit;

sub runMigrations {
    # Migrate a parameter file.
    my $fileName = $_;
    chomp($fileName);
    # Only consider XML files.
    return
	unless ( $fileName =~ m/\.xml$/ );
    # Ignore certain paths.
    return
	if ( $File::Find::dir =~ m/constraints\/parameters/ || $File::Find::dir =~ m/constraints\/dataAnalysis/ || $File::Find::dir =~ m/testSuite\/outputs/ );
    # Parse XML and ignore any non-parameter files.
    my $parser = XML::LibXML->new();
    my $doc   = $parser->parse_file($fileName);
    return
	unless ( $doc->findnodes('//parameters') );    
    # Migrate the parameter file.
    system("cd ".$ENV{'GALACTICUS_EXEC_PATH'}."; ./scripts/aux/parametersMigrate.pl ".$File::Find::name." migration__.xml.tmp --ignoreWhiteSpaceChanges yes --validate no --timeStamp ".$timeStamp);
    # Clean up.
    mv($ENV{'GALACTICUS_EXEC_PATH'}."/migration__.xml.tmp",$File::Find::name);
    return;
}
