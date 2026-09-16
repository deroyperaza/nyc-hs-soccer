import re

SPECIAL = {
 'The Bronx High School of Science': 'Bronx Science',
 'Fiorello H. LaGuardia High School of Music & Art and Performing Arts': 'LaGuardia',
 'New Explorations into Science, Technology and Math High School': 'NEST+m',
 'The Michael J. Petrides School': 'Petrides',
 'Edward R. Murrow High School': 'Murrow',
 'Franklin Delano Roosevelt High School': 'FDR',
 'McKee/Staten Island Tech': 'McKee/SI Tech',
 'Brooklyn Technical High School': 'Brooklyn Tech',
 'High School for Mathematics, Science and Engineering at City College': 'HSMSE',
 'High School of American Studies at Lehman College': 'HS American Studies',
 'Manhattan Center for Science and Mathematics': 'Manhattan Center',
 'Hunter College High School': 'Hunter College',
 'Bard High School Early College - Manhattan': 'Bard Manhattan',
 'Bard High School Early College - Queens': 'Bard Queens',
 'Frank Sinatra School of the Arts': 'Frank Sinatra',
 'Benjamin N. Cardozo High School': 'Cardozo',
 'Martin Luther King, Jr. Educational Campus': 'MLK Campus',
 'Martin L. King Jr': 'Martin L. King',
 'Fort Hamilton High School': 'Fort Hamilton',
 'Francis Lewis High School': 'Francis Lewis',
 'Forest Hills High School': 'Forest Hills',
 'Abraham Lincoln High School': 'Lincoln',
 'John Dewey High School': 'John Dewey',
 'James Madison High School': 'Madison',
 'New Utrecht High School': 'New Utrecht',
 'DeWitt Clinton High School': 'DeWitt Clinton',
 'Tottenville High School': 'Tottenville',
 'Curtis High School': 'Curtis',
 'Susan E. Wagner High School': 'Susan Wagner',
 'Port Richmond High School': 'Port Richmond',
 'Beacon High School': 'Beacon',
 'Stuyvesant High School': 'Stuyvesant',
 'Midwood High School': 'Midwood',
 'South Shore HS': 'South Shore',
 'Washington Irving HS': 'Washington Irving',
 'Louis Brandeis': 'Brandeis',
 'Lab Museum United': 'Lab Museum',
 'Grand Street Campus': 'Grand Street',
 'Erasmus Hall Campus': 'Erasmus Hall',
 'John Jay Campus': 'John Jay',
 'Thomas Jefferson Campus': 'Thomas Jefferson',
 'Evander Childs Campus': 'Evander Childs',
 'George Westinghouse': 'Westinghouse',
 'Frederick Douglass Academy': 'F. Douglass Academy',
 'Queens Gateway to Health Sciences Secondary School': 'Queens Gateway',
 'Academy for Careers In Television and Film': 'Careers in TV & Film',
 'Columbia Secondary School': 'Columbia Secondary',
 'Graphics Campus': 'Graphics',
}

def shorten(name, limit=24):
    n = (name or '').strip()
    if n in SPECIAL:
        return SPECIAL[n]
    s = n
    s = re.sub(r'^The\s+', '', s)
    s = re.sub(r'\s*\(.*?\)\s*$', '', s)
    if len(s) > limit and ' - ' in s:
        s = s.split(' - ')[0]
    s = re.sub(r'\s+Educational Campus$', '', s, flags=re.I)
    s = re.sub(r'\s+(Senior\s+)?High\s+School$', '', s, flags=re.I)
    s = re.sub(r'\s+H\.?\s?S\.?$', '', s, flags=re.I)
    s = re.sub(r'\s+Secondary\s+School$', '', s, flags=re.I)
    s = re.sub(r'\s+Campus$', '', s, flags=re.I)
    s = re.sub(r'\s+School$', '', s, flags=re.I)
    s = re.sub(r'\s+High\s+School\s+', ' ', s, flags=re.I)
    s = re.sub(r'^High\s+School\s+(for|of)\s+(the\s+)?', 'HS ', s, flags=re.I)
    if len(s) > limit and ',' in s:
        s = s.split(',')[0]
    if len(s) > limit and ' at ' in s:
        s = s.split(' at ')[0]
    s = s.strip(' ,-')
    if len(s) > limit + 4:
        cut = s[:limit]
        if ' ' in cut:
            cut = cut[:cut.rfind(' ')]
        s = cut.strip(' ,-')
    return s or n
