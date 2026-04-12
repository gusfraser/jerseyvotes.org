"""
AgenticGov Analytics Engine
Computes voting alignment, blocs, independence scores, and political spectrum.
"""

import os
import json
from collections import defaultdict

import numpy as np
import psycopg2
from dotenv import load_dotenv
from scipy.cluster.hierarchy import linkage, fcluster
from scipy.spatial.distance import squareform
from sklearn.decomposition import PCA

load_dotenv()


def get_connection():
    return psycopg2.connect(os.environ['DATABASE_URL'])


def fetch_vote_matrix(conn, term='current', stage_filter=('principles', 'third_reading')):
    """
    Build a member-vote matrix for alignment analysis.
    Returns: member_names (list), division_ids (list), matrix (numpy array)
    Matrix values: +1 (Pour), -1 (Contre), 0 (Abstained), NaN (absent/not eligible)
    """
    cur = conn.cursor()

    # Get eligible divisions
    stage_clause = ''
    params = []
    if stage_filter:
        placeholders = ','.join(['%s'] * len(stage_filter))
        stage_clause = f'AND vd.division_stage IN ({placeholders})'
        params.extend(stage_filter)

    date_clause = ''
    if term == 'current':
        date_clause = "AND vd.date >= '2022-07-01'"  # Current term started ~mid 2022

    query = f'''
        SELECT vd.division_id
        FROM vote_divisions vd
        WHERE 1=1 {stage_clause} {date_clause}
        ORDER BY vd.date
    '''
    cur.execute(query, params)
    division_ids = [row[0] for row in cur.fetchall()]

    if not division_ids:
        print('No divisions found for the given filter.')
        return [], [], np.array([])

    # Get active members for the period
    if term == 'current':
        cur.execute('SELECT member_id, canonical_name FROM members WHERE is_currently_active ORDER BY canonical_name')
    else:
        cur.execute('SELECT member_id, canonical_name FROM members ORDER BY canonical_name')
    members = cur.fetchall()
    member_ids = [m[0] for m in members]
    member_names = [m[1] for m in members]

    # Build the matrix
    div_idx = {d: i for i, d in enumerate(division_ids)}
    mem_idx = {m: i for i, m in enumerate(member_ids)}

    matrix = np.full((len(member_ids), len(division_ids)), np.nan)

    placeholders = ','.join(['%s'] * len(division_ids))
    cur.execute(f'''
        SELECT division_id, member_id, vote
        FROM votes
        WHERE division_id IN ({placeholders})
        AND vote IN ('Pour', 'Contre', 'Abstained')
    ''', division_ids)

    for div_id, mem_id, vote in cur.fetchall():
        if mem_id in mem_idx and div_id in div_idx:
            val = 1 if vote == 'Pour' else (-1 if vote == 'Contre' else 0)
            matrix[mem_idx[mem_id], div_idx[div_id]] = val

    cur.close()
    print(f'Vote matrix: {len(member_names)} members x {len(division_ids)} divisions '
          f'({stage_filter}, {term} term)')
    return member_names, division_ids, matrix


def compute_pairwise_alignment(member_names, matrix):
    """
    Compute pairwise agreement percentage between all members.
    Only counts divisions where both members cast an active vote (Pour or Contre).
    """
    n = len(member_names)
    agreement = np.zeros((n, n))
    shared_votes = np.zeros((n, n), dtype=int)

    for i in range(n):
        for j in range(i, n):
            # Only compare where both voted Pour or Contre (not abstained or absent)
            mask_i = np.isin(matrix[i], [1, -1])
            mask_j = np.isin(matrix[j], [1, -1])
            shared = mask_i & mask_j

            count = np.sum(shared)
            if count > 0:
                agree = np.sum(matrix[i, shared] == matrix[j, shared])
                agreement[i, j] = agree / count
                agreement[j, i] = agreement[i, j]
                shared_votes[i, j] = count
                shared_votes[j, i] = count
            else:
                agreement[i, j] = np.nan
                agreement[j, i] = np.nan

    return agreement, shared_votes


def compute_cosine_similarity(matrix):
    """Compute cosine similarity between members, treating NaN as 0."""
    filled = np.nan_to_num(matrix, nan=0.0)
    norms = np.linalg.norm(filled, axis=1, keepdims=True)
    norms[norms == 0] = 1  # Avoid division by zero
    normalized = filled / norms
    return normalized @ normalized.T


def find_voting_blocs(member_names, cosine_sim, n_clusters=5):
    """Hierarchical clustering to find voting blocs."""
    # Convert similarity to distance
    distance = 1 - cosine_sim
    np.fill_diagonal(distance, 0)
    distance = np.clip(distance, 0, None)  # Ensure non-negative

    condensed = squareform(distance)
    Z = linkage(condensed, method='ward')
    labels = fcluster(Z, t=n_clusters, criterion='maxclust')

    blocs = defaultdict(list)
    for name, label in zip(member_names, labels):
        blocs[label].append(name)

    return blocs, Z, labels


def compute_pca(matrix, n_components=3):
    """PCA for political spectrum positioning."""
    filled = np.nan_to_num(matrix, nan=0.0)
    pca = PCA(n_components=n_components)
    coords = pca.fit_transform(filled)
    return coords, pca.explained_variance_ratio_


def compute_independence_scores(member_names, matrix, division_ids, conn):
    """How often each member votes against the majority."""
    cur = conn.cursor()

    # Get majority outcome for each division
    placeholders = ','.join(['%s'] * len(division_ids))
    cur.execute(f'''
        SELECT division_id,
               CASE WHEN pour_count >= contre_count THEN 1 ELSE -1 END as majority
        FROM vote_divisions
        WHERE division_id IN ({placeholders})
    ''', division_ids)
    majority = {row[0]: row[1] for row in cur.fetchall()}
    cur.close()

    scores = {}
    for i, name in enumerate(member_names):
        dissent = 0
        total = 0
        for j, div_id in enumerate(division_ids):
            vote = matrix[i, j]
            if vote in (1, -1) and div_id in majority:
                total += 1
                if vote != majority[div_id]:
                    dissent += 1
        scores[name] = {
            'dissent_rate': dissent / total if total > 0 else 0,
            'dissent_count': dissent,
            'total_active_votes': total
        }

    return scores


def compute_participation_rates(conn, term='current'):
    """Compute participation and attendance stats per member."""
    cur = conn.cursor()

    date_clause = "AND vd.date >= '2022-07-01'" if term == 'current' else ''

    cur.execute(f'''
        SELECT m.canonical_name,
               COUNT(*) as total_divisions,
               SUM(CASE WHEN v.vote_category = 'active_vote' THEN 1 ELSE 0 END) as active_votes,
               SUM(CASE WHEN v.vote_category = 'excused_absence' THEN 1 ELSE 0 END) as excused,
               SUM(CASE WHEN v.vote_category = 'unexcused_absence' THEN 1 ELSE 0 END) as unexcused,
               SUM(CASE WHEN v.vote = 'Abstained' THEN 1 ELSE 0 END) as abstentions
        FROM votes v
        JOIN members m ON v.member_id = m.member_id
        JOIN vote_divisions vd ON v.division_id = vd.division_id
        WHERE m.is_currently_active {date_clause}
        GROUP BY m.canonical_name
        ORDER BY m.canonical_name
    ''')

    results = {}
    for row in cur.fetchall():
        name, total, active, excused, unexcused, abstentions = row
        results[name] = {
            'total_divisions': total,
            'active_votes': active,
            'excused_absences': excused,
            'unexcused_absences': unexcused,
            'abstentions': abstentions,
            'participation_rate': active / total if total > 0 else 0,
            'unexcused_rate': unexcused / total if total > 0 else 0,
        }

    cur.close()
    return results


def main():
    conn = get_connection()

    print('=== AgenticGov Voting Analysis ===\n')

    # 1. Build vote matrix (current term, principles + third reading only)
    member_names, division_ids, matrix = fetch_vote_matrix(conn, term='current')

    if len(member_names) == 0:
        print('No data to analyse.')
        return

    # 2. Pairwise alignment
    print('\n--- Pairwise Alignment (Agreement %) ---')
    agreement, shared = compute_pairwise_alignment(member_names, matrix)

    # Show top 10 most aligned pairs
    pairs = []
    for i in range(len(member_names)):
        for j in range(i + 1, len(member_names)):
            if shared[i, j] >= 50:  # Minimum 50 shared votes
                pairs.append((member_names[i], member_names[j], agreement[i, j], shared[i, j]))

    pairs.sort(key=lambda x: -x[2])
    print('\nTop 15 most aligned pairs:')
    for a, b, pct, n in pairs[:15]:
        print(f'  {a:25s} <-> {b:25s}  {pct:.1%} ({n} shared votes)')

    print('\nTop 15 least aligned pairs:')
    pairs.sort(key=lambda x: x[2])
    for a, b, pct, n in pairs[:15]:
        print(f'  {a:25s} <-> {b:25s}  {pct:.1%} ({n} shared votes)')

    # 3. Cosine similarity and voting blocs
    print('\n--- Voting Blocs (Hierarchical Clustering) ---')
    cosine_sim = compute_cosine_similarity(matrix)
    blocs, Z, labels = find_voting_blocs(member_names, cosine_sim, n_clusters=5)

    for bloc_id, members in sorted(blocs.items()):
        print(f'\nBloc {bloc_id} ({len(members)} members):')
        for m in sorted(members):
            print(f'  {m}')

    # 4. PCA / Political Spectrum
    print('\n--- Political Spectrum (PCA) ---')
    coords, variance_ratio = compute_pca(matrix)
    print(f'Variance explained: PC1={variance_ratio[0]:.1%}, PC2={variance_ratio[1]:.1%}, PC3={variance_ratio[2]:.1%}')

    print('\nMember positions (PC1, PC2):')
    sorted_by_pc1 = sorted(zip(member_names, coords), key=lambda x: x[1][0])
    for name, (pc1, pc2, pc3) in sorted_by_pc1:
        bar = '|' + '.' * int((pc1 + 5) * 4) + '*' + '.' * int((5 - pc1) * 4) + '|'
        print(f'  {name:25s}  PC1={pc1:+.2f}  PC2={pc2:+.2f}  {bar}')

    # 5. Independence scores
    print('\n--- Independence Scores (Majority Dissent Rate) ---')
    independence = compute_independence_scores(member_names, matrix, division_ids, conn)
    sorted_ind = sorted(independence.items(), key=lambda x: -x[1]['dissent_rate'])
    for name, data in sorted_ind:
        print(f'  {name:25s}  {data["dissent_rate"]:.1%} dissent ({data["dissent_count"]}/{data["total_active_votes"]} votes)')

    # 6. Participation rates
    print('\n--- Participation Rates (Current Term) ---')
    participation = compute_participation_rates(conn, term='current')
    sorted_part = sorted(participation.items(), key=lambda x: -x[1]['participation_rate'])
    for name, data in sorted_part:
        print(f'  {name:25s}  {data["participation_rate"]:.1%} participation, '
              f'{data["unexcused_rate"]:.1%} unexcused absence '
              f'({data["active_votes"]}/{data["total_divisions"]} votes)')

    conn.close()
    print('\nDone!')


if __name__ == '__main__':
    main()
