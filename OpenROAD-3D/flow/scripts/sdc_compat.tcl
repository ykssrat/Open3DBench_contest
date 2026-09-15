# Preserve real bus ports; repair only an exact missing scalar[0] reference.
proc contest_scalar_port_aliases {args} {
  if {[llength $args] == 1} {
    set patterns [lindex $args 0]
    set corrected {}
    set block [ord::get_db_block]
    foreach pattern $patterns {
      if {[regexp {^([[:alnum:]_]+)\[0\]$} $pattern -> scalar]
          && [$block findBTerm $pattern] eq "NULL"
          && [$block findBTerm $scalar] ne "NULL"} {
        puts "STA scalar port alias: $pattern -> $scalar"
        lappend corrected $scalar
      } else {
        lappend corrected $pattern
      }
    }
    set args [list $corrected]
  }
  return [::sta::contest_original_get_ports {*}$args]
}

proc contest_with_scalar_port_aliases {script} {
  # Nested reads can occur when older stage scripts also wrap load_design.
  if {[info exists ::contest_sdc_alias_active]} {
    return [uplevel 1 $script]
  }
  rename ::get_ports ::contest_original_global_get_ports
  rename ::sta::get_ports ::sta::contest_original_get_ports
  interp alias {} ::sta::get_ports {} contest_scalar_port_aliases
  interp alias {} ::get_ports {} contest_scalar_port_aliases
  set ::contest_sdc_alias_active 1
  try {
    uplevel 1 $script
  } finally {
    rename ::get_ports {}
    rename ::sta::get_ports {}
    rename ::sta::contest_original_get_ports ::sta::get_ports
    rename ::contest_original_global_get_ports ::get_ports
    unset ::contest_sdc_alias_active
  }
}

proc read_sdc_compat {args} {
  contest_with_scalar_port_aliases { read_sdc {*}$args }
}
