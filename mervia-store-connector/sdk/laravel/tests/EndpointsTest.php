<?php

namespace Mervia\StoreConnector\Tests;

use Illuminate\Support\Facades\Route;
use Mervia\StoreConnector\Http\Requests\CreateArticleRequest;
use Mervia\StoreConnector\Http\Requests\PutProductContentRequest;
use Mervia\StoreConnector\Http\Requests\UpdateArticleRequest;
use Mervia\StoreConnector\Http\Resources\ArticleResource;

class EndpointsTest extends TestCase
{
    protected function defineRoutes($router): void
    {
        Route::prefix('api/mervia/v1')->middleware('mervia.auth')->group(function () {
            Route::get('/store', fn () => ['store_id' => 'example-us']);
            Route::post('/articles', fn (CreateArticleRequest $r) => response()->json($r->validated(), 201));
            Route::patch('/articles/{id}', fn (UpdateArticleRequest $r) => $r->validated());
            Route::put('/products/{id}/content', fn (PutProductContentRequest $r) => response()->noContent());
        });
    }

    public function test_accepts_the_current_and_the_previous_key(): void
    {
        $this->getJson('/api/mervia/v1/store', ['Authorization' => 'Bearer key-current'])->assertOk();
        $this->getJson('/api/mervia/v1/store', ['Authorization' => 'Bearer key-previous'])->assertOk();
    }

    public function test_refuses_a_wrong_or_missing_key_in_the_contract_error_shape(): void
    {
        $this->getJson('/api/mervia/v1/store', ['Authorization' => 'Bearer nope'])
            ->assertStatus(401)->assertJson(['error' => 'unauthorized']);
        $this->getJson('/api/mervia/v1/store')->assertStatus(401);
    }

    public function test_no_configured_key_refuses_everything(): void
    {
        config(['mervia.api_key_for_mervia' => null, 'mervia.api_key_for_mervia_previous' => null]);
        $this->getJson('/api/mervia/v1/store', ['Authorization' => 'Bearer '])->assertStatus(401);
    }

    private function auth(): array
    {
        return ['Authorization' => 'Bearer key-current'];
    }

    public function test_create_article_validation(): void
    {
        $ok = ['type' => 'post', 'title' => 'Best example widgets', 'body_html' => '<p>x</p>', 'tags' => ['mervia', 'mervia-case-12']];
        $this->postJson('/api/mervia/v1/articles', $ok, $this->auth())->assertCreated();

        $this->postJson('/api/mervia/v1/articles', $ok + ['status' => 'published'], $this->auth())
            ->assertStatus(422)->assertJson(['error' => 'invalid']);
        $this->postJson('/api/mervia/v1/articles', ['type' => 'news'] + $ok, $this->auth())->assertStatus(422);
        $this->postJson('/api/mervia/v1/articles', $ok + ['featured_image_url' => 'http://x.test/a.png'], $this->auth())->assertStatus(422);
        $this->postJson('/api/mervia/v1/articles', ['type' => 'post'], $this->auth())->assertStatus(422);
    }

    public function test_update_article_validation(): void
    {
        $this->patchJson('/api/mervia/v1/articles/5', ['status' => 'published'], $this->auth())->assertOk();
        $this->patchJson('/api/mervia/v1/articles/5', ['status' => 'live'], $this->auth())->assertStatus(422);
    }

    public function test_put_product_content_allows_empty_parts(): void
    {
        $this->putJson('/api/mervia/v1/products/9/content', ['version' => 2, 'head_html' => '', 'body_html' => '<section></section>'], $this->auth())
            ->assertNoContent();
        $this->putJson('/api/mervia/v1/products/9/content', ['version' => 0, 'head_html' => '', 'body_html' => ''], $this->auth())
            ->assertStatus(422);
        $this->putJson('/api/mervia/v1/products/9/content', ['version' => 1, 'body_html' => ''], $this->auth())
            ->assertStatus(422);
    }

    public function test_article_resource_digest_tracks_body_only(): void
    {
        $article = (object) ['id' => 5, 'type' => 'post', 'title' => 'T', 'slug' => 't', 'excerpt' => null, 'body_html' => '<p>x</p>',
            'author' => null, 'tags' => ['mervia'], 'featured_image_url' => null, 'meta_title' => null, 'meta_description' => null,
            'status' => 'hidden', 'published_at' => null, 'created_at' => now(), 'updated_at' => now()];

        $out = (new ArticleResource($article))->resolve();
        $this->assertSame('sha256:' . hash('sha256', '<p>x</p>'), $out['content_digest']);
        $this->assertSame('5', $out['id']);
        foreach (['id', 'type', 'title', 'slug', 'url', 'body_html', 'status', 'content_digest', 'created_at', 'updated_at'] as $key) {
            $this->assertNotNull($out[$key], $key);
        }

        $article->title = 'Changed';
        $this->assertSame($out['content_digest'], (new ArticleResource($article))->resolve()['content_digest']);
    }
}
