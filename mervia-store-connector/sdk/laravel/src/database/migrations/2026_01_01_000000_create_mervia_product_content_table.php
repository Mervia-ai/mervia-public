<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

// Item 6: one row per product for the document Mervia pushes to PUT /products/{id}/content.
return new class extends Migration
{
    public function up(): void
    {
        Schema::create($this->table(), function (Blueprint $table) {
            $table->string('product_id', 191)->primary();
            $table->unsignedBigInteger('version');
            $table->longText('head_html');
            $table->longText('body_html');
            $table->timestamp('updated_at')->nullable();
        });
    }

    public function down(): void
    {
        Schema::dropIfExists($this->table());
    }

    private function table(): string
    {
        return (string) config('mervia.content_table', 'mervia_product_content');
    }
};
