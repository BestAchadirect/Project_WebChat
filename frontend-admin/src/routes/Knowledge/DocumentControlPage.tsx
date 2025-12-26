import React, { useState, useEffect } from 'react';
import { chunksApi, Chunk, ArticleChunkGroup, SimilarityResult } from '../../api/training';

export const DocumentControlPage: React.FC = () => {
    const [articles, setArticles] = useState<ArticleChunkGroup[]>([]);
    const [loading, setLoading] = useState(true);
    const [searchQuery, setSearchQuery] = useState('');
    const [selectedChunk, setSelectedChunk] = useState<Chunk | null>(null);
    const [editedText, setEditedText] = useState('');
    const [saving, setSaving] = useState(false);
    const [expandedArticles, setExpandedArticles] = useState<Set<string>>(new Set());
    const [selectedChunks, setSelectedChunks] = useState<Set<string>>(new Set());
    const [bulkProcessing, setBulkProcessing] = useState(false);

    // Similarity test state
    const [testQuery, setTestQuery] = useState('');
    const [testResults, setTestResults] = useState<SimilarityResult[]>([]);
    const [testing, setTesting] = useState(false);
    const [showTestPanel, setShowTestPanel] = useState(false);

    const [editingArticleId, setEditingArticleId] = useState<string | null>(null);
    const [renamingTitle, setRenamingTitle] = useState('');

    const [totalArticles, setTotalArticles] = useState(0);
    const [totalChunks, setTotalChunks] = useState(0);

    useEffect(() => {
        loadArticles();
    }, []);

    const loadArticles = async (search?: string) => {
        try {
            setLoading(true);
            const result = await chunksApi.listArticlesGrouped(search || undefined);
            setArticles(result.articles);
            setTotalArticles(result.total_articles);
            setTotalChunks(result.total_chunks);
            // Expand all articles by default
            setExpandedArticles(new Set(result.articles.map(a => a.article_id)));
        } catch (error) {
            console.error('Failed to load articles:', error);
        } finally {
            setLoading(false);
        }
    };

    const handleRename = async (articleId: string) => {
        if (!renamingTitle.trim()) return;
        try {
            await chunksApi.renameArticle(articleId, renamingTitle);
            setArticles(articles.map(a =>
                a.article_id === articleId ? { ...a, article_title: renamingTitle } : a
            ));
            setEditingArticleId(null);
        } catch (error) {
            console.error('Failed to rename article:', error);
            alert('Failed to rename article');
        }
    };

    const handleSearch = () => {
        loadArticles(searchQuery);
    };

    const toggleArticleExpand = (articleId: string) => {
        const newSet = new Set(expandedArticles);
        if (newSet.has(articleId)) {
            newSet.delete(articleId);
        } else {
            newSet.add(articleId);
        }
        setExpandedArticles(newSet);
    };

    const handleCollapseAll = () => {
        setExpandedArticles(new Set());
    };

    const handleExpandAll = () => {
        setExpandedArticles(new Set(articles.map(a => a.article_id)));
    };

    const handleChunkClick = (chunk: Chunk) => {
        setSelectedChunk(chunk);
        setEditedText(chunk.chunk_text);
    };

    const handleSave = async () => {
        if (!selectedChunk) return;

        try {
            setSaving(true);
            await chunksApi.updateChunk(selectedChunk.id, { chunk_text: editedText });
            await chunksApi.reembedChunk(selectedChunk.id);

            // Reload to get fresh data
            await loadArticles(searchQuery);
            setSelectedChunk({ ...selectedChunk, chunk_text: editedText, is_embedded: true });

            alert('Chunk saved and re-embedded successfully!');
        } catch (error) {
            console.error('Failed to save chunk:', error);
            alert('Failed to save chunk');
        } finally {
            setSaving(false);
        }
    };

    const toggleChunkSelection = (chunkId: string) => {
        const newSet = new Set(selectedChunks);
        if (newSet.has(chunkId)) {
            newSet.delete(chunkId);
        } else {
            newSet.add(chunkId);
        }
        setSelectedChunks(newSet);
    };

    const selectAllInArticle = (articleId: string) => {
        const article = articles.find(a => a.article_id === articleId);
        if (!article) return;

        const newSet = new Set(selectedChunks);
        const allSelected = article.chunks.every(c => newSet.has(c.id));

        if (allSelected) {
            article.chunks.forEach(c => newSet.delete(c.id));
        } else {
            article.chunks.forEach(c => newSet.add(c.id));
        }
        setSelectedChunks(newSet);
    };

    const handleBulkReembed = async () => {
        if (selectedChunks.size === 0) return;
        if (!confirm(`Re-embed ${selectedChunks.size} chunks? This may take a while.`)) return;

        try {
            setBulkProcessing(true);
            const result = await chunksApi.bulkReembed(Array.from(selectedChunks));
            alert(result.message);
            setSelectedChunks(new Set());
            await loadArticles(searchQuery);
        } catch (error) {
            console.error('Bulk re-embed failed:', error);
            alert('Bulk re-embed failed');
        } finally {
            setBulkProcessing(false);
        }
    };

    const handleBulkDelete = async () => {
        if (selectedChunks.size === 0) return;
        if (!confirm(`Delete ${selectedChunks.size} chunks? This cannot be undone.`)) return;

        try {
            setBulkProcessing(true);
            const result = await chunksApi.bulkDelete(Array.from(selectedChunks));
            alert(result.message);
            setSelectedChunks(new Set());
            setSelectedChunk(null);
            await loadArticles(searchQuery);
        } catch (error) {
            console.error('Bulk delete failed:', error);
            alert('Bulk delete failed');
        } finally {
            setBulkProcessing(false);
        }
    };

    const handleSimilarityTest = async () => {
        if (!testQuery.trim()) return;

        try {
            setTesting(true);
            const result = await chunksApi.testSimilarity(testQuery, 10);
            setTestResults(result.results);
        } catch (error) {
            console.error('Similarity test failed:', error);
            alert('Similarity test failed');
        } finally {
            setTesting(false);
        }
    };

    return (
        <div className="space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-2xl font-bold text-gray-900">Document Control</h1>
                    <p className="text-sm text-gray-500">{totalArticles} Articles • {totalChunks} Chunks</p>
                </div>
                <button
                    onClick={() => setShowTestPanel(!showTestPanel)}
                    className={`px-4 py-2 rounded-lg flex items-center gap-2 ${showTestPanel ? 'bg-primary-100 text-primary-700' : 'bg-gray-100 text-gray-700'
                        }`}
                >
                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                    </svg>
                    Similarity Test
                </button>
            </div>

            {/* Search & Bulk Actions */}
            <div className="flex flex-wrap gap-4 items-center bg-white p-4 rounded-xl shadow-sm border border-gray-200">
                <div className="flex gap-2">
                    <button
                        onClick={handleExpandAll}
                        className="px-3 py-2 text-sm bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 flex items-center gap-1"
                        title="Expand All"
                    >
                        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                        </svg>
                        Expand All
                    </button>
                    <button
                        onClick={handleCollapseAll}
                        className="px-3 py-2 text-sm bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 flex items-center gap-1"
                        title="Collapse All"
                    >
                        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                        </svg>
                        Collapse All
                    </button>
                </div>

                <div className="flex gap-2 flex-1">
                    <input
                        type="text"
                        placeholder="Search chunks..."
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                        className="flex-1 px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
                    />
                    <button onClick={handleSearch} className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700">
                        Search
                    </button>
                </div>

                {selectedChunks.size > 0 && (
                    <div className="flex gap-2">
                        <button
                            onClick={handleBulkReembed}
                            disabled={bulkProcessing}
                            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
                        >
                            Re-embed ({selectedChunks.size})
                        </button>
                        <button
                            onClick={handleBulkDelete}
                            disabled={bulkProcessing}
                            className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50"
                        >
                            Delete ({selectedChunks.size})
                        </button>
                        <button
                            onClick={() => setSelectedChunks(new Set())}
                            className="px-4 py-2 bg-gray-200 text-gray-700 rounded-lg hover:bg-gray-300"
                        >
                            Clear
                        </button>
                    </div>
                )}
            </div>

            {/* Similarity Test Panel */}
            {showTestPanel && (
                <div className="bg-gradient-to-r from-purple-50 to-indigo-50 p-6 rounded-xl border border-purple-200">
                    <h2 className="text-lg font-semibold text-purple-900 mb-4">Similarity Test</h2>
                    <div className="flex gap-4 mb-4">
                        <input
                            type="text"
                            placeholder="Enter a test query..."
                            value={testQuery}
                            onChange={(e) => setTestQuery(e.target.value)}
                            onKeyDown={(e) => e.key === 'Enter' && handleSimilarityTest()}
                            className="flex-1 px-4 py-2 border border-purple-300 rounded-lg focus:ring-2 focus:ring-purple-500"
                        />
                        <button
                            onClick={handleSimilarityTest}
                            disabled={testing}
                            className="px-6 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50"
                        >
                            {testing ? 'Testing...' : 'Test'}
                        </button>
                    </div>

                    {testResults.length > 0 && (
                        <div className="space-y-2 max-h-64 overflow-y-auto">
                            {testResults.map((result) => (
                                <div key={result.chunk_id} className="flex items-start gap-3 p-3 bg-white rounded-lg border border-purple-100">
                                    <div className={`px-2 py-1 rounded text-sm font-bold ${result.similarity_score > 0.8 ? 'bg-green-100 text-green-700' :
                                        result.similarity_score > 0.6 ? 'bg-yellow-100 text-yellow-700' :
                                            'bg-gray-100 text-gray-700'
                                        }`}>
                                        {(result.similarity_score * 100).toFixed(1)}%
                                    </div>
                                    <div className="flex-1 min-w-0">
                                        <div className="text-xs text-purple-600 mb-1">{result.article_title}</div>
                                        <p className="text-sm text-gray-700 line-clamp-2">{result.chunk_text}</p>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}

            <div className="flex gap-6">
                {/* Article List */}
                <div className="flex-1">
                    {loading ? (
                        <div className="flex items-center justify-center py-12">
                            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
                        </div>
                    ) : (
                        <div className="space-y-4">
                            {articles.map((article) => (
                                <div key={article.article_id} className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
                                    {/* Article Header */}
                                    <div
                                        className="flex items-center justify-between p-4 bg-gray-50 cursor-pointer hover:bg-gray-100"
                                        onClick={() => toggleArticleExpand(article.article_id)}
                                    >
                                        <div className="flex items-center gap-3">
                                            <svg
                                                className={`w-5 h-5 text-gray-500 transition-transform ${expandedArticles.has(article.article_id) ? 'rotate-90' : ''}`}
                                                fill="none" viewBox="0 0 24 24" stroke="currentColor"
                                            >
                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                                            </svg>
                                            <div onClick={(e) => e.stopPropagation()} className="flex-1">
                                                {editingArticleId === article.article_id ? (
                                                    <input
                                                        autoFocus
                                                        type="text"
                                                        value={renamingTitle}
                                                        onChange={(e) => setRenamingTitle(e.target.value)}
                                                        onBlur={() => handleRename(article.article_id)}
                                                        onKeyDown={(e) => {
                                                            if (e.key === 'Enter') handleRename(article.article_id);
                                                            if (e.key === 'Escape') setEditingArticleId(null);
                                                        }}
                                                        className="w-full px-2 py-1 border border-primary-500 rounded text-sm font-semibold text-gray-900 focus:outline-none"
                                                    />
                                                ) : (
                                                    <div className="flex items-center gap-2 group">
                                                        <h3
                                                            className="font-semibold text-gray-900 hover:text-primary-600 transition-colors"
                                                            onClick={() => {
                                                                setEditingArticleId(article.article_id);
                                                                setRenamingTitle(article.article_title);
                                                            }}
                                                        >
                                                            {article.article_title}
                                                        </h3>
                                                        <button
                                                            className="opacity-0 group-hover:opacity-100 p-1 hover:bg-gray-200 rounded transition-opacity"
                                                            onClick={() => {
                                                                setEditingArticleId(article.article_id);
                                                                setRenamingTitle(article.article_title);
                                                            }}
                                                        >
                                                            <svg className="w-4 h-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                                                            </svg>
                                                        </button>
                                                    </div>
                                                )}
                                                <p className="text-xs text-gray-500">{article.chunk_count} chunks • {article.category || 'No category'}</p>
                                            </div>
                                        </div>
                                        <button
                                            onClick={(e) => { e.stopPropagation(); selectAllInArticle(article.article_id); }}
                                            className="text-xs text-primary-600 hover:text-primary-800"
                                        >
                                            Select All
                                        </button>
                                    </div>

                                    {/* Chunks */}
                                    {expandedArticles.has(article.article_id) && (
                                        <div className="divide-y divide-gray-100">
                                            {article.chunks.map((chunk) => (
                                                <div
                                                    key={chunk.id}
                                                    className={`list-group-item flex items-start gap-3 p-4 cursor-pointer transition-all hover:bg-gray-50 ${selectedChunk?.id === chunk.id ? 'bg-primary-50 border-l-4 border-primary-500' : ''
                                                        }`}
                                                >
                                                    <input
                                                        type="checkbox"
                                                        checked={selectedChunks.has(chunk.id)}
                                                        onChange={() => toggleChunkSelection(chunk.id)}
                                                        onClick={(e) => e.stopPropagation()}
                                                        className="mt-1 rounded border-gray-300"
                                                    />
                                                    <div className="flex-1 min-w-0" onClick={() => handleChunkClick(chunk)}>
                                                        <div className="flex items-center gap-2 mb-1">
                                                            <span className="text-xs font-mono bg-gray-100 px-2 py-0.5 rounded">
                                                                #{chunk.chunk_index}
                                                            </span>
                                                            <span className={`text-xs px-2 py-0.5 rounded ${chunk.is_embedded ? 'bg-green-100 text-green-700' : 'bg-yellow-100 text-yellow-700'
                                                                }`}>
                                                                {chunk.is_embedded ? '✓ Embedded' : '⚠ Not Embedded'}
                                                            </span>
                                                            <span className="text-xs text-gray-400">{chunk.char_count} chars</span>
                                                        </div>
                                                        <p className="text-sm text-gray-700 line-clamp-2">{chunk.chunk_text}</p>
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            ))}

                            {articles.length === 0 && (
                                <div className="text-center py-12 text-gray-500 bg-white rounded-xl">
                                    No articles found
                                </div>
                            )}
                        </div>
                    )}
                </div>

                {/* Chunk Detail Panel */}
                {selectedChunk && (
                    <div className="w-96 bg-white rounded-xl shadow-sm border border-gray-200 p-6 sticky top-6 h-fit">
                        <div className="flex items-center justify-between mb-4">
                            <h2 className="text-lg font-bold text-gray-900">Edit Chunk</h2>
                            <button onClick={() => setSelectedChunk(null)} className="p-1 hover:bg-gray-100 rounded">
                                <svg className="w-5 h-5 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                                </svg>
                            </button>
                        </div>

                        <div className="space-y-4">
                            <div className="grid grid-cols-2 gap-2 text-xs">
                                <div className="bg-gray-50 p-2 rounded">
                                    <span className="text-gray-500">Index:</span> <span className="font-medium">{selectedChunk.chunk_index}</span>
                                </div>
                                <div className="bg-gray-50 p-2 rounded">
                                    <span className="text-gray-500">Version:</span> <span className="font-medium">{selectedChunk.version}</span>
                                </div>
                                <div className="bg-gray-50 p-2 rounded">
                                    <span className="text-gray-500">Chars:</span> <span className="font-medium">{editedText.length}</span>
                                </div>
                                <div className="bg-gray-50 p-2 rounded">
                                    <span className={`${selectedChunk.is_embedded ? 'text-green-600' : 'text-yellow-600'}`}>
                                        {selectedChunk.is_embedded ? '✓ Embedded' : '⚠ Not Embedded'}
                                    </span>
                                </div>
                            </div>

                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-2">Chunk Text</label>
                                <textarea
                                    value={editedText}
                                    onChange={(e) => setEditedText(e.target.value)}
                                    rows={12}
                                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 resize-none text-sm"
                                />
                            </div>

                            <button
                                onClick={handleSave}
                                disabled={saving || editedText === selectedChunk.chunk_text}
                                className="w-full px-4 py-3 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50 flex items-center justify-center gap-2"
                            >
                                {saving ? (
                                    <><div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white"></div> Saving...</>
                                ) : (
                                    <><svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                                    </svg> Save & Re-embed</>
                                )}
                            </button>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};
