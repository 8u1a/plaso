# -*- coding: utf-8 -*-
"""This file contains a appfirewall.log (Mac OS X Firewall) parser."""

import datetime
import logging

import pyparsing

from plaso.events import time_events
from plaso.lib import eventdata
from plaso.lib import timelib
from plaso.parsers import manager
from plaso.parsers import text_parser


__author__ = 'Joaquin Moreno Garijo (Joaquin.MorenoGarijo.2013@live.rhul.ac.uk)'


class MacAppFirewallLogEvent(time_events.TimestampEvent):
  """Convenience class for a Mac Wifi log line event."""

  DATA_TYPE = u'mac:asl:appfirewall:line'

  def __init__(self, timestamp, structure, process_name, action):
    """Initializes the event object.

    Args:
      timestamp: The timestamp which is an integer containing the number
                 of micro seconds since January 1, 1970, 00:00:00 UTC.
      structure: structure with the parse fields.
          computer_name: string with the name of the computer.
          agent: string with the agent that save the log.
          status: string with the saved status action.
          process_name: string name of the entity that tried do the action.
      action: string with the action
    """
    super(MacAppFirewallLogEvent, self).__init__(
        timestamp, eventdata.EventTimestamp.ADDED_TIME)
    self.action = action
    self.agent = structure.agent
    self.computer_name = structure.computer_name
    self.process_name = process_name
    self.status = structure.status


class MacAppFirewallParser(text_parser.PyparsingSingleLineTextParser):
  """Parse text based on appfirewall.log file."""

  NAME = u'mac_appfirewall_log'
  DESCRIPTION = u'Parser for appfirewall.log files.'

  ENCODING = u'utf-8'

  # Regular expressions for known actions.

  # Define how a log line should look like.
  # Example: 'Nov  2 04:07:35 DarkTemplar-2.local socketfilterfw[112] '
  #          '<Info>: Dropbox: Allow (in:0 out:2)'
  # INFO: process_name is going to have a white space at the beginning.
  FIREWALL_LINE = (
      text_parser.PyparsingConstants.MONTH.setResultsName(u'month') +
      text_parser.PyparsingConstants.ONE_OR_TWO_DIGITS.setResultsName(u'day') +
      text_parser.PyparsingConstants.TIME.setResultsName(u'time') +
      pyparsing.Word(pyparsing.printables).setResultsName(u'computer_name') +
      pyparsing.Word(pyparsing.printables).setResultsName(u'agent') +
      pyparsing.Literal(u'<').suppress() +
      pyparsing.CharsNotIn(u'>').setResultsName(u'status') +
      pyparsing.Literal(u'>:').suppress() +
      pyparsing.CharsNotIn(u':').setResultsName(u'process_name') +
      pyparsing.Literal(u':') +
      pyparsing.SkipTo(pyparsing.lineEnd).setResultsName(u'action'))

  # Repeated line.
  # Example: Nov 29 22:18:29 --- last message repeated 1 time ---
  REPEATED_LINE = (
      text_parser.PyparsingConstants.MONTH.setResultsName(u'month') +
      text_parser.PyparsingConstants.ONE_OR_TWO_DIGITS.setResultsName(u'day') +
      text_parser.PyparsingConstants.TIME.setResultsName(u'time') +
      pyparsing.Literal(u'---').suppress() +
      pyparsing.CharsNotIn(u'---').setResultsName(u'process_name') +
      pyparsing.Literal(u'---').suppress())

  # Define the available log line structures.
  LINE_STRUCTURES = [
      (u'logline', FIREWALL_LINE),
      (u'repeated', REPEATED_LINE)]

  def __init__(self):
    """Initializes a parser object."""
    super(MacAppFirewallParser, self).__init__()
    self._year_use = 0
    self._last_month = None
    self.previous_structure = None

  def VerifyStructure(self, parser_mediator, line):
    """Verify that this file is a Mac AppFirewall log file.

    Args:
      parser_mediator: A parser mediator object (instance of ParserMediator).
      line: A single line from the text file.

    Returns:
      True if this is the correct parser, False otherwise.
    """
    try:
      line = self.FIREWALL_LINE.parseString(line)
    except pyparsing.ParseException:
      logging.debug(u'Not a Mac AppFirewall log file')
      return False
    if (line.action != u'creating /var/log/appfirewall.log' or
        line.status != u'Error'):
      return False
    return True

  def ParseRecord(self, parser_mediator, key, structure):
    """Parses a log record structure and produces events.

    Args:
      parser_mediator: A parser mediator object (instance of ParserMediator).
      key: An identification string indicating the name of the parsed
           structure.
      structure: A pyparsing.ParseResults object from a line in the
                 log file.
    """
    if key in [u'logline', u'repeated']:
      self._ParseLogLine(parser_mediator, structure, key)
    else:
      logging.warning(
          u'Unable to parse record, unknown structure: {0:s}'.format(key))

  def _ParseLogLine(self, parser_mediator, structure, key):
    """Parse a single log line and produce an event object.

    Args:
      parser_mediator: A parser mediator object (instance of ParserMediator).
      structure: log line of structure.
      key: type of line log (normal or repeated).
    """
    # TODO: improve this to get a valid year.
    if not self._year_use:
      self._year_use = parser_mediator.year

    if not self._year_use:
      # Get from the creation time of the file.
      self._year_use = self._GetYear(
          self.file_entry.GetStat(), parser_mediator.timezone)
      # If fail, get from the current time.
      if not self._year_use:
        self._year_use = timelib.GetCurrentYear()

    # Gap detected between years.
    month = timelib.MONTH_DICT.get(structure.month.lower())
    if not self._last_month:
      self._last_month = month
    if month < self._last_month:
      self._year_use += 1
    timestamp = self._GetTimestamp(
        structure.day,
        month,
        self._year_use,
        structure.time)
    if not timestamp:
      logging.debug(u'Invalid timestamp {0:s}'.format(structure.timestamp))
      return
    self._last_month = month

    # If the actual entry is a repeated entry, we take the basic information
    # from the previous entry, but using the timestmap from the actual entry.
    if key == u'logline':
      self.previous_structure = structure
    else:
      structure = self.previous_structure

    # Pyparsing reads in RAW, but the text is in UTF8.
    try:
      action = structure.action.decode(u'utf-8')
    except UnicodeDecodeError:
      logging.warning(
          u'Decode UTF8 failed, the message string may be cut short.')
      action = structure.action.decode(u'utf-8', u'ignore')
    # Due to the use of CharsNotIn pyparsing structure contains whitespaces
    # that need to be removed.
    process_name = structure.process_name.strip()

    event_object = MacAppFirewallLogEvent(
        timestamp, structure, process_name, action)
    parser_mediator.ProduceEvent(event_object)

  def _GetTimestamp(self, day, month, year, time):
    """Gets a timestamp from a pyparsing ParseResults timestamp.

    This is a timestamp_string as returned by using
    text_parser.PyparsingConstants structures:
    08, Nov, [20, 36, 37]

    Args:
      timestamp_string: The pyparsing ParseResults object

    Returns:
      day: An integer representing the day.
      month: An integer representing the month.
      year: An integer representing the year.
      timestamp: A plaso timelib timestamp event or 0.
    """
    try:
      hour, minute, second = time
      timestamp = timelib.Timestamp.FromTimeParts(
          year, month, day, hour, minute, second)
    except ValueError:
      timestamp = 0
    return timestamp

  def _GetYear(self, stat, timezone):
    """Retrieves the year either from the input file or from the settings."""
    time = getattr(stat, u'crtime', 0)
    if not time:
      time = getattr(stat, u'ctime', 0)

    if not time:
      logging.error(
          u'Unable to determine correct year of log file, defaulting to '
          u'current year.')
      return timelib.GetCurrentYear()

    try:
      timestamp = datetime.datetime.fromtimestamp(time, timezone)
    except ValueError as exception:
      logging.error((
          u'Unable to determine correct year of log file with error: {0:s}, '
          u'defaulting to current year.').format(exception))
      return timelib.GetCurrentYear()
    return timestamp.year


manager.ParsersManager.RegisterParser(MacAppFirewallParser)
