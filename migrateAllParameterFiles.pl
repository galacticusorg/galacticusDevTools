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
    # Pre-process the file to concatenate any attribute values that are split across multiple lines.
    open(my $fileInput ,"<",$fileName       );
    open(my $fileOutput,">",$fileName.".tmp");
    my $inMultiline = 0;
    my $inComment = 0;
    while ( my $line = <$fileInput> ) {
	my $countQuotes = $line =~ tr/"//;
	$inComment = 1
	    if ( $line =~ m/<!\-\-/ );
	$inMultiline = 1-$inMultiline
	    if ( $countQuotes % 2 == 1 && ! $inComment );
	$line =~ s/\n/\%\%NEWLINE\%\%/
	    if ( $inMultiline          && ! $inComment );
	$inComment = 0
	    if ( $line =~ m/\-\->/ );
	print $fileOutput $line;
    }
    close($fileInput );
    close($fileOutput);
    # Migrate the parameter file.
    system("cd ".$ENV{'GALACTICUS_EXEC_PATH'}."; ./scripts/aux/parametersMigrate.pl ".$File::Find::name.".tmp migration__.xml.tmp --validate no --timeStamp ".$timeStamp);
    # Make a patch from the old to the new file, but ignoring changes in whitespace.
    system("cd ".$ENV{'GALACTICUS_EXEC_PATH'}."; diff -w -u ".$File::Find::name.".tmp migration__.xml.tmp > tmp__.patch");
    # Apply the patch to the old file - we now have migrations applied, but no change in whitespace formatting.
    system("cd ".$ENV{'GALACTICUS_EXEC_PATH'}."; patch ".$File::Find::name.".tmp tmp__.patch");
    # Undo any split line reformatting that we previously applied.
    open(my $migratedFileInput ,"<",$fileName.".tmp");
    open(my $migratedFileOutput,">",$fileName       );
    while ( my $line = <$migratedFileInput> ) {
	$line =~ s/\%\%NEWLINE\%\%/\n/g;
	print $migratedFileOutput $line;
    }
    close($migratedFileInput );
    close($migratedFileOutput);
    # Clean up.
    unlink($fileName.".tmp",$ENV{'GALACTICUS_EXEC_PATH'}."/tmp__.patch",$ENV{'GALACTICUS_EXEC_PATH'}."/migration__.xml.tmp");
    return;
}
