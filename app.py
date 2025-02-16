from flask import Flask, jsonify, request
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import re
from functools import lru_cache
import statistics
from flask_cors import CORS

app = Flask(__name__)
CORS(app, resources={
    r"/api/*": {
        "origins": ["*"],  # Allow all origins for development
        "methods": ["GET", "POST", "OPTIONS"],  # Allowed methods
        "allow_headers": ["Content-Type", "Authorization"]  # Allowed headers
    }
})

CONTRIBUTION_COLORS = {
    0: "#ebedf0",
    1: "#9be9a8",
    2: "#40c463",
    3: "#30a14e",
    4: "#216e39"
}

@lru_cache(maxsize=100)
def fetch_github_data(username, from_date, to_date):
    url = f"https://github.com/users/{username}/contributions?from={from_date}&to={to_date}"
    response = requests.get(url)
    
    if response.status_code == 404:
        raise ValueError("GitHub user not found")
    elif response.status_code != 200:
        raise ValueError("Failed to fetch GitHub data")
    with open("response.html", "w", encoding="utf-8") as f:
        f.write(response.text)
    return response.text

def parse_contribution_data(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    contributions = []
    current_date = datetime.now().date()
    
    for td in soup.find_all('td', class_='ContributionCalendar-day'):
        date = td.get('data-date')
        if not date:
            continue
        
        # Convert the date string to a date object
        date_obj = datetime.strptime(date, '%Y-%m-%d').date()
        
        # Skip contributions beyond the current date
        if date_obj > current_date:
            continue
        
        tooltip_id = td.get('id')
        tooltip = soup.find('tool-tip', {'for': tooltip_id})
        if not tooltip:
            continue
        
        count_text = tooltip.text.strip()
        count_match = re.search(r'(\d+) contributions?', count_text)
        count = int(count_match.group(1)) if count_match else 0
        
        level = int(td.get('data-level', 0))
        
        contributions.append({
            'date': date,
            'contributions': count,
            'colorCode': CONTRIBUTION_COLORS[level],
            'description': count_text
        })
    
    # Sort contributions by date in ascending order
    contributions.sort(key=lambda x: x['date'])
    
    return contributions

def calculate_statistics(contributions):
    if not contributions:
        return {}
        
    contribution_counts = [c['contributions'] for c in contributions]
    
    return {
        'total_contributions': sum(contribution_counts),
        'average_daily_contributions': round(statistics.mean(contribution_counts), 2),
        'median_daily_contributions': statistics.median(contribution_counts),
        'max_contributions_day': max(contributions, key=lambda x: x['contributions']),
        'streak': calculate_longest_streak(contributions),
        'active_days': len([c for c in contribution_counts if c > 0]),
        'inactive_days': len([c for c in contribution_counts if c == 0])
    }

def calculate_longest_streak(contributions):
    current_streak = 0
    longest_streak = 0
    streak_end_date = None
    
    for contrib in contributions:
        if contrib['contributions'] > 0:
            current_streak += 1
            if current_streak > longest_streak:
                longest_streak = current_streak
                streak_end_date = contrib['date']
        else:
            current_streak = 0
            
    return {
        'length': longest_streak,
        'end_date': streak_end_date
    }

@app.route('/api/contributions')
def get_contributions():
    try:
        username = request.args.get('username')
        if not username:
            return jsonify({'error': 'Username is required'}), 400
            
        year = request.args.get('year')
        from_date = request.args.get('from')
        to_date = request.args.get('to')
        
        if year:
            from_date = f"{year}-01-01"
            to_date = f"{year}-12-31"
        elif not (from_date and to_date):
            return jsonify({'error': 'Either year or both from_date and to_date are required'}), 400
            
        try:
            from_date_obj = datetime.strptime(from_date, '%Y-%m-%d').date()
            to_date_obj = datetime.strptime(to_date, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400
            
        html_content = fetch_github_data(username, from_date, to_date)
        contributions = parse_contribution_data(html_content)
        
        # Filter contributions to only include those within the specified date range
        contributions = [
            c for c in contributions
            if from_date_obj <= datetime.strptime(c['date'], '%Y-%m-%d').date() <= to_date_obj
        ]
        
        statistics = calculate_statistics(contributions)
        
        return jsonify({
            'username': username,
            'period': {
                'from': from_date,
                'to': to_date
            },
            'contributions': contributions,
            'statistics': statistics
        })
        
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/profile/<username>')
def get_profile_stats(username):
    try:
        url = f"https://github.com/{username}"
        response = requests.get(url)
        
        if response.status_code == 404:
            return jsonify({'error': 'User not found'}), 404
            
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Get contribution stats
        stats = {}
        contribution_boxes = soup.find_all('div', class_='js-yearly-contributions')
        for box in contribution_boxes:
            h2_tags = box.find_all('h2')
            for h2 in h2_tags:
                if 'contributions' in h2.text.lower():
                    stats['total_contributions_last_year'] = int(re.search(r'(\d+)', h2.text).group(1))
                    
        # Get repository stats
        nav_items = soup.find_all('span', class_='Counter')
        if nav_items:
            stats['repositories'] = int(nav_items[0].text.strip())
            
        # Get followers and following
        stats['followers'] = int(soup.find('span', class_='text-bold color-fg-default', text=re.compile(r'followers')).text.strip())
        stats['following'] = int(soup.find('span', class_='text-bold color-fg-default', text=re.compile(r'following')).text.strip())
        
        return jsonify({
            'username': username,
            'stats': stats
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/repositories/<username>')
def get_repositories(username):
    try:
        url = f"https://github.com/{username}?tab=repositories"
        response = requests.get(url)
        
        if response.status_code == 404:
            return jsonify({'error': 'User not found'}), 404
            
        soup = BeautifulSoup(response.text, 'html.parser')
        repos = []
        
        for repo in soup.find_all('li', {'class': 'col-12 d-flex width-full py-4 border-bottom color-border-muted public source'}):
            name_tag = repo.find('a', {'itemprop': 'name codeRepository'})
            if name_tag:
                name = name_tag.text.strip()
                description = repo.find('p', {'class': 'col-9 d-inline-block text-gray mb-2 pr-4'})
                description = description.text.strip() if description else ''
                language = repo.find('span', {'itemprop': 'programmingLanguage'})
                language = language.text.strip() if language else ''
                
                repos.append({
                    'name': name,
                    'description': description,
                    'language': language
                })
        
        return jsonify({
            'username': username,
            'repositories': repos
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=6969, debug=True)